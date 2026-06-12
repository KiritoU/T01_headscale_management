import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentModule, AgentType, CommandState
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker():
    return Worker.objects.create(name="worker-poll", hostname="poll.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-poll",
        headscale_host="hs.example.com",
        headplane_host="hp.example.com",
        db_name="hs_team_poll",
        worker=worker,
    )


@pytest.fixture
def gateway(tenant):
    return Gateway.objects.create(tenant=tenant, hostname="gw-poll")


def _auth_header(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.mark.django_db
class TestAgentRegister:
    def test_register_worker_agent(self, client, worker):
        response = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert "agent_id" in body
        assert "token" in body
        assert body["token"].startswith("agnt_")
        assert body["poll_interval_seconds"] == 15

        agent = Agent.objects.get(id=body["agent_id"])
        assert agent.agent_type == AgentType.WORKER
        worker.refresh_from_db()
        assert worker.agent_id == agent.id
        assert agent.token_hash
        assert agent.token_hash != body["token"]

    def test_register_gateway_agent(self, client, gateway):
        response = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.GATEWAY, "gateway_id": str(gateway.id)},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        agent = Agent.objects.get(id=body["agent_id"])
        gateway.refresh_from_db()
        assert gateway.agent_id == agent.id


@pytest.mark.django_db
class TestAgentHeartbeat:
    def test_heartbeat_updates_modules_and_inventory(self, client, worker):
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        before = timezone.now()
        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={
                "installed_modules": [
                    {"module_id": "docker", "status": "installed", "version": "24.0"},
                    {"module_id": "compose", "status": "installed"},
                ],
                "docker_reachable": True,
                "tenant_inventory": {"tenants": ["team-poll"]},
            },
            content_type="application/json",
            **_auth_header(token),
        )

        assert response.status_code == 200
        agent = Agent.objects.get(id=agent_id)
        assert agent.last_seen_at >= before
        assert agent.tenant_inventory == {"tenants": ["team-poll"]}

        worker.refresh_from_db()
        assert worker.docker_reachable is True
        assert worker.last_heartbeat_at >= before

        modules = AgentModule.objects.filter(agent=agent).order_by("name")
        assert modules.count() == 2
        assert modules[0].name == "compose"
        assert modules[1].name == "docker"

    def test_heartbeat_requires_auth(self, client, worker):
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        agent_id = reg.json()["agent_id"]

        response = client.post(
            reverse("agent-heartbeat", kwargs={"agent_id": agent_id}),
            data={"installed_modules": []},
            content_type="application/json",
        )

        assert response.status_code == 403


@pytest.mark.django_db
class TestAgentPollAckFlow:
    def test_full_poll_ack_flow_install_module(self, client, worker):
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        enqueue = client.post(
            reverse("agent-command-enqueue", kwargs={"agent_id": agent_id}),
            data={
                "command": "install_module",
                "payload": {"module": "tailscale"},
            },
            content_type="application/json",
        )
        assert enqueue.status_code == 201
        enqueue_body = enqueue.json()
        assert enqueue_body["success"] is True
        cmd_id = enqueue_body["data"]["id"]

        cmd = AgentCommand.objects.get(id=cmd_id)
        assert cmd.state == CommandState.PENDING

        poll = client.get(
            reverse("agent-poll", kwargs={"agent_id": agent_id}),
            **_auth_header(token),
        )
        assert poll.status_code == 200
        poll_body = poll.json()
        assert len(poll_body["commands"]) == 1
        assert poll_body["commands"][0]["id"] == cmd_id
        assert poll_body["commands"][0]["command"] == "install_module"
        assert poll_body["commands"][0]["payload"] == {"module": "tailscale"}

        cmd.refresh_from_db()
        assert cmd.state == CommandState.DISPATCHED
        assert cmd.dispatched_at is not None

        second_poll = client.get(
            reverse("agent-poll", kwargs={"agent_id": agent_id}),
            **_auth_header(token),
        )
        assert second_poll.json()["commands"] == []

        ack = client.post(
            reverse("agent-command-ack", kwargs={"agent_id": agent_id, "cmd_id": cmd_id}),
            data={
                "state": "acked",
                "result": {
                    "exit_code": 0,
                    "duration_ms": 1200,
                    "logs": "module installed",
                },
            },
            content_type="application/json",
            **_auth_header(token),
        )
        assert ack.status_code == 200

        cmd.refresh_from_db()
        assert cmd.state == CommandState.ACKED
        assert cmd.result == {
            "exit_code": 0,
            "duration_ms": 1200,
            "logs": "module installed",
        }
        assert cmd.acked_at is not None

    def test_ack_provision_updates_tenant_runtime_status(self, client, worker):
        from tenants.models import RuntimeStatus, Tenant

        tenant = Tenant.objects.create(
            slug="ack-sync-1",
            headscale_host="headscale-ack-sync-1.example.com",
            headplane_host="headplane-ack-sync-1.example.com",
            db_name="hs_ack_sync_1",
            worker=worker,
            runtime_status=RuntimeStatus.PROVISIONING,
        )
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]
        worker.agent_id = agent_id
        worker.save(update_fields=["agent"])

        enqueue = client.post(
            reverse("agent-command-enqueue", kwargs={"agent_id": agent_id}),
            data={
                "command": "provision_tenant",
                "payload": {"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            },
            content_type="application/json",
        )
        cmd_id = enqueue.json()["data"]["id"]
        client.get(reverse("agent-poll", kwargs={"agent_id": agent_id}), **_auth_header(token))

        ack = client.post(
            reverse("agent-command-ack", kwargs={"agent_id": agent_id, "cmd_id": cmd_id}),
            data={
                "state": "acked",
                "result": {
                    "exit_code": 0,
                    "duration_ms": 1000,
                    "logs": "ok",
                    "runtime_status": RuntimeStatus.RUNNING,
                },
            },
            content_type="application/json",
            **_auth_header(token),
        )
        assert ack.status_code == 200
        tenant.refresh_from_db()
        assert tenant.runtime_status == RuntimeStatus.RUNNING

    def test_ack_provision_result_includes_runtime_fields(self, client, worker):
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        enqueue = client.post(
            reverse("agent-command-enqueue", kwargs={"agent_id": agent_id}),
            data={"command": "provision_tenant", "payload": {"tenant_slug": "team-1"}},
            content_type="application/json",
        )
        cmd_id = enqueue.json()["data"]["id"]
        client.get(reverse("agent-poll", kwargs={"agent_id": agent_id}), **_auth_header(token))

        ack = client.post(
            reverse("agent-command-ack", kwargs={"agent_id": agent_id, "cmd_id": cmd_id}),
            data={
                "state": "acked",
                "result": {
                    "exit_code": 0,
                    "duration_ms": 5000,
                    "logs": "provision complete",
                    "runtime_status": "running",
                    "config_ref": "/opt/headscale-worker-stack/tenants/team-1",
                },
            },
            content_type="application/json",
            **_auth_header(token),
        )
        assert ack.status_code == 200

    def test_ack_failed_state(self, client, worker):
        reg = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        token = reg.json()["token"]
        agent_id = reg.json()["agent_id"]

        enqueue = client.post(
            reverse("agent-command-enqueue", kwargs={"agent_id": agent_id}),
            data={"command": "install_module", "payload": {"module": "nmap"}},
            content_type="application/json",
        )
        cmd_id = enqueue.json()["data"]["id"]

        client.get(reverse("agent-poll", kwargs={"agent_id": agent_id}), **_auth_header(token))

        ack = client.post(
            reverse("agent-command-ack", kwargs={"agent_id": agent_id, "cmd_id": cmd_id}),
            data={
                "state": "failed",
                "result": {"exit_code": 1, "duration_ms": 500, "logs": "install error"},
            },
            content_type="application/json",
            **_auth_header(token),
        )
        assert ack.status_code == 200

        cmd = AgentCommand.objects.get(id=cmd_id)
        assert cmd.state == CommandState.FAILED

    def test_poll_wrong_agent_token_rejected(self, client, worker):
        reg1 = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER, "worker_id": str(worker.id)},
            content_type="application/json",
        )
        reg2 = client.post(
            reverse("agent-register"),
            data={"agent_type": AgentType.WORKER},
            content_type="application/json",
        )

        response = client.get(
            reverse("agent-poll", kwargs={"agent_id": reg1.json()["agent_id"]}),
            **_auth_header(reg2.json()["token"]),
        )
        assert response.status_code == 403

    def test_enqueue_not_found_returns_envelope(self, client):
        response = client.post(
            reverse("agent-command-enqueue", kwargs={"agent_id": uuid.uuid4()}),
            data={"command": "install_module", "payload": {"module": "tailscale"}},
            content_type="application/json",
        )

        assert response.status_code == 404
        body = response.json()
        assert body["success"] is False
        assert body["error"]
