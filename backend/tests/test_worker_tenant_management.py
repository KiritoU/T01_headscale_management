from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentType, CommandState
from agents.services import ack_command
from lifecycle.services import enqueue_bootstrap_tenant
from tenants.detail import HEALTH_CHECK_HISTORY_LIMIT
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant, TenantHealth
from workers.models import Worker, WorkerStatus
from workers.tenant_services import (
    WorkerTenantError,
    assert_worker_ready,
    bulk_create_tenants,
    bulk_provision_pending_tenants,
    enqueue_provision_tenant,
    enqueue_start_tenant,
    enqueue_stop_tenant,
    get_tenant_summary,
    remove_tenant,
    sync_tenant_from_acked_command,
    sync_tenant_runtime_from_command,
)


@pytest.fixture
def ready_worker(db):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_tm1",
        token_hash="b" * 64,
    )
    return Worker.objects.create(
        name="tenant-worker",
        hostname="tenant.vps.example.com",
        status=WorkerStatus.ONLINE,
        docker_reachable=True,
        agent=agent,
    )


@pytest.fixture
def pending_tenant(ready_worker):
    return Tenant.objects.create(
        slug="team-1",
        headscale_host="headscale-team-1.example.com",
        headplane_host="headplane-team-1.example.com",
        db_name="hs_team_1",
        worker=ready_worker,
        desired_config={"dns": {"magic_dns_base": "tailnet-team-1.example.com"}},
        runtime_status=RuntimeStatus.PENDING,
    )


@pytest.mark.django_db
class TestWorkerTenantServices:
    def test_assert_worker_ready_passes(self, ready_worker):
        assert_worker_ready(ready_worker)

    def test_assert_worker_ready_fails_when_offline(self, ready_worker):
        Worker.objects.filter(pk=ready_worker.pk).update(status=WorkerStatus.OFFLINE)
        ready_worker.refresh_from_db()

        with pytest.raises(WorkerTenantError, match="not online"):
            assert_worker_ready(ready_worker)

    def test_assert_worker_ready_fails_without_docker(self, ready_worker):
        Worker.objects.filter(pk=ready_worker.pk).update(docker_reachable=False)
        ready_worker.refresh_from_db()

        with pytest.raises(WorkerTenantError, match="Docker"):
            assert_worker_ready(ready_worker)

    def test_assert_worker_ready_fails_without_agent(self, db):
        worker = Worker.objects.create(
            name="no-agent-worker",
            status=WorkerStatus.ONLINE,
            docker_reachable=True,
        )

        with pytest.raises(WorkerTenantError, match="no registered agent"):
            assert_worker_ready(worker)

    def test_bulk_create_tenants(self, ready_worker):
        tenants = bulk_create_tenants(
            ready_worker,
            suffix="team",
            start_number=1,
            count=3,
            base_domain="example.com",
        )

        assert len(tenants) == 3
        assert [tenant.slug for tenant in tenants] == ["team-1", "team-2", "team-3"]
        assert all(tenant.runtime_status == RuntimeStatus.PENDING for tenant in tenants)
        assert all(tenant.worker_id == ready_worker.id for tenant in tenants)

    def test_enqueue_provision_sets_runtime_status_and_config_refs(
        self,
        pending_tenant,
        ready_worker,
    ):
        command = enqueue_provision_tenant(pending_tenant)

        assert command.command == "provision_tenant"
        pending_tenant.refresh_from_db()
        assert pending_tenant.runtime_status == RuntimeStatus.PROVISIONING

        stored = AgentCommand.objects.get(id=command.id)
        assert stored.payload["tenant_slug"] == "team-1"
        assert stored.payload["config_ref"] == (f"worker-config://{ready_worker.id}/tenants/team-1")
        assert stored.payload["production"] is False
        assert isinstance(stored.payload["headscale_config"], dict)
        assert stored.payload["headscale_config"]["database"]["postgres"]["name"] == "hs_team_1"
        assert isinstance(stored.payload["compose_snippet"], str)
        assert "headscale-team-1:" in stored.payload["compose_snippet"]
        assert stored.payload["login_server"] == "http://headscale-team-1.example.com"
        assert stored.payload["client_scripts"]["linux.sh"]
        assert stored.payload["client_scripts"]["gateway.sh"]

    def test_enqueue_provision_skips_duplicate_pending(self, pending_tenant):
        first = enqueue_provision_tenant(pending_tenant)
        second = enqueue_provision_tenant(pending_tenant)

        assert second.skipped is True
        assert second.id == first.id
        assert AgentCommand.objects.filter(command="provision_tenant").count() == 1

    def test_enqueue_start_and_stop(self, pending_tenant, ready_worker):
        start = enqueue_start_tenant(pending_tenant)
        stop = enqueue_stop_tenant(pending_tenant)

        assert start.command == "start_tenant"
        assert stop.command == "stop_tenant"
        assert (
            AgentCommand.objects.filter(
                agent=ready_worker.agent,
                command__in=["start_tenant", "stop_tenant"],
            ).count()
            == 2
        )

    def test_bulk_provision_pending_tenants(self, ready_worker):
        bulk_create_tenants(
            ready_worker,
            suffix="bulk",
            start_number=1,
            count=2,
            base_domain="example.com",
        )
        Tenant.objects.filter(worker=ready_worker, slug="bulk-1").update(
            runtime_status=RuntimeStatus.RUNNING,
        )

        commands = bulk_provision_pending_tenants(ready_worker)

        assert len(commands) == 1
        assert commands[0].command == "provision_tenant"
        assert AgentCommand.objects.filter(command="provision_tenant").count() == 1

    def test_get_tenant_summary(self, ready_worker, pending_tenant):
        Tenant.objects.create(
            slug="team-2",
            headscale_host="headscale-team-2.example.com",
            headplane_host="headplane-team-2.example.com",
            db_name="hs_team_2",
            worker=ready_worker,
            bootstrap_status=BootstrapStatus.BOOTSTRAPPED,
            runtime_status=RuntimeStatus.RUNNING,
        )

        summary = get_tenant_summary(ready_worker)

        assert summary.total == 2
        assert summary.bootstrap_status[BootstrapStatus.PENDING] == 1
        assert summary.bootstrap_status[BootstrapStatus.BOOTSTRAPPED] == 1
        assert summary.runtime_status[RuntimeStatus.PENDING] == 1
        assert summary.runtime_status[RuntimeStatus.RUNNING] == 1

    def test_remove_tenant_deletes_record(self, ready_worker, pending_tenant):
        tenant_id = pending_tenant.id

        remove_tenant(ready_worker, pending_tenant)

        assert not Tenant.objects.filter(id=tenant_id).exists()

    def test_remove_running_tenant_enqueues_stop(self, ready_worker, pending_tenant):
        Tenant.objects.filter(pk=pending_tenant.pk).update(runtime_status=RuntimeStatus.RUNNING)

        remove_tenant(ready_worker, pending_tenant)

        assert AgentCommand.objects.filter(command="stop_tenant").exists()
        assert not Tenant.objects.filter(id=pending_tenant.id).exists()

    def test_sync_tenant_runtime_from_command(self, pending_tenant, ready_worker):
        command = enqueue_provision_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )
        stored.refresh_from_db()

        sync_tenant_runtime_from_command(stored, pending_tenant)

        pending_tenant.refresh_from_db()
        assert pending_tenant.runtime_status == RuntimeStatus.RUNNING

    def test_sync_tenant_runtime_marks_failed_on_command_failure(
        self,
        pending_tenant,
        ready_worker,
    ):
        command = enqueue_provision_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(stored, state=CommandState.FAILED, result={"exit_code": 1})

        sync_tenant_runtime_from_command(stored, pending_tenant)

        pending_tenant.refresh_from_db()
        assert pending_tenant.runtime_status == RuntimeStatus.FAILED

    def test_sync_tenant_bootstrap_from_command(self, pending_tenant, ready_worker):
        command = enqueue_bootstrap_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
            },
        )
        stored.refresh_from_db()

        sync_tenant_runtime_from_command(stored, pending_tenant)

        pending_tenant.refresh_from_db()
        assert pending_tenant.bootstrap_status == BootstrapStatus.BOOTSTRAPPED

    def test_sync_tenant_bootstrap_marks_failed_on_command_failure(
        self,
        pending_tenant,
        ready_worker,
    ):
        command = enqueue_bootstrap_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(stored, state=CommandState.FAILED, result={"exit_code": 1})

        sync_tenant_runtime_from_command(stored, pending_tenant)

        pending_tenant.refresh_from_db()
        assert pending_tenant.bootstrap_status == BootstrapStatus.FAILED


@pytest.mark.django_db
class TestWorkerTenantApi:
    def test_get_tenant_summary(self, client, ready_worker, pending_tenant):
        response = client.get(
            reverse("worker-tenant-summary", kwargs={"worker_id": ready_worker.id}),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["runtime_status"][RuntimeStatus.PENDING] == 1

    def test_list_tenants(self, client, ready_worker, pending_tenant):
        response = client.get(
            reverse("worker-tenant-list", kwargs={"worker_id": ready_worker.id}),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["slug"] == "team-1"
        assert body["data"][0]["runtime_status"] == RuntimeStatus.PENDING

    def test_bulk_create_tenants(self, client, ready_worker):
        response = client.post(
            reverse("worker-tenant-bulk-create", kwargs={"worker_id": ready_worker.id}),
            data={
                "suffix": "api",
                "start_number": 10,
                "count": 2,
                "base_domain": "example.com",
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert [item["slug"] for item in body["data"]] == ["api-10", "api-11"]

    def test_bulk_create_rejects_duplicate_slug(self, client, ready_worker):
        Tenant.objects.create(
            slug="remote-1",
            headscale_host="headscale-remote-1.remote.local",
            headplane_host="headplane-remote-1.remote.local",
            db_name="hs_remote_1",
            worker=ready_worker,
            desired_config={"production": False},
            runtime_status=RuntimeStatus.PENDING,
        )

        response = client.post(
            reverse("worker-tenant-bulk-create", kwargs={"worker_id": ready_worker.id}),
            data={
                "suffix": "remote",
                "start_number": 1,
                "count": 3,
                "base_domain": "remote.local",
                "production": False,
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "remote-1" in body["error"]
        assert Tenant.objects.filter(slug="remote-2").exists() is False

    def test_bulk_create_rejects_mixed_production_modes(self, client, ready_worker):
        Tenant.objects.create(
            slug="dev-1",
            headscale_host="headscale-dev-1.example.com",
            headplane_host="headplane-dev-1.example.com",
            db_name="hs_dev_1",
            worker=ready_worker,
            desired_config={"production": False},
            runtime_status=RuntimeStatus.PENDING,
        )

        response = client.post(
            reverse("worker-tenant-bulk-create", kwargs={"worker_id": ready_worker.id}),
            data={
                "suffix": "prod",
                "start_number": 1,
                "count": 1,
                "base_domain": "example.com",
                "production": True,
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "Cannot mix production and dev tenants" in body["error"]

    def test_bulk_provision_pending(self, client, ready_worker):
        bulk_create_tenants(
            ready_worker,
            suffix="prov",
            start_number=1,
            count=2,
            base_domain="example.com",
        )

        response = client.post(
            reverse("worker-tenant-bulk-provision", kwargs={"worker_id": ready_worker.id}),
        )

        assert response.status_code == 202
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert AgentCommand.objects.filter(command="provision_tenant").count() == 2

    def test_provision_tenant(self, client, ready_worker, pending_tenant):
        response = client.post(
            reverse(
                "worker-tenant-provision",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert response.status_code == 202
        body = response.json()
        assert body["success"] is True
        assert body["data"]["command"] == "provision_tenant"
        assert body["data"]["runtime_status"] == RuntimeStatus.PROVISIONING

    def test_start_and_stop_tenant(self, client, ready_worker, pending_tenant):
        start = client.post(
            reverse(
                "worker-tenant-start",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        stop = client.post(
            reverse(
                "worker-tenant-stop",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert start.status_code == 202
        assert stop.status_code == 202
        assert start.json()["data"]["command"] == "start_tenant"
        assert stop.json()["data"]["command"] == "stop_tenant"

    def test_verify_and_bootstrap_delegate_to_lifecycle(
        self,
        client,
        ready_worker,
        pending_tenant,
    ):
        verify = client.post(
            reverse(
                "worker-tenant-verify",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        bootstrap = client.post(
            reverse(
                "worker-tenant-bootstrap",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert verify.status_code == 202
        assert bootstrap.status_code == 202
        assert verify.json()["data"]["command"] == "verify_tenant"
        assert bootstrap.json()["data"]["bootstrap_status"] == BootstrapStatus.PROVISIONING

    def test_get_worker_tenant_detail_returns_bootstrap_info_and_health_checks(
        self,
        client,
        ready_worker,
        pending_tenant,
    ):
        bootstrap = enqueue_bootstrap_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=bootstrap.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "api_key": "hskey-api-detail",
                    "auth_key_gateway": "hskey-gateway-detail",
                    "auth_key_workspace": "hskey-workspace-detail",
                    "admin_user_id": "admin-detail",
                    "output_ref": pending_tenant.bootstrap_output_ref,
                },
            },
        )
        for index in range(HEALTH_CHECK_HISTORY_LIMIT + 1):
            TenantHealth.objects.create(
                tenant=pending_tenant,
                probed_at=timezone.now() - timezone.timedelta(minutes=index),
                latency_ms=index * 10,
                healthy=index % 2 == 0,
            )

        response = client.get(
            reverse(
                "worker-tenant-detail",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["bootstrap_info"] is not None
        assert data["bootstrap_info"]["api_key"] == "hskey-api-detail"
        assert data["bootstrap_info"]["auth_key_gateway"] == "hskey-gateway-detail"
        assert data["bootstrap_info"]["auth_key_workspace"] == "hskey-workspace-detail"
        assert len(data["health_checks"]) == HEALTH_CHECK_HISTORY_LIMIT

    def test_provision_ack_auto_enqueues_bootstrap(self, ready_worker, pending_tenant):
        command = enqueue_provision_tenant(pending_tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )
        stored.refresh_from_db()

        sync_tenant_from_acked_command(stored)

        assert AgentCommand.objects.filter(
            agent=ready_worker.agent,
            command="bootstrap_tenant",
            payload__tenant_id=str(pending_tenant.id),
        ).exists()
        pending_tenant.refresh_from_db()
        assert pending_tenant.runtime_status == RuntimeStatus.RUNNING
        assert pending_tenant.bootstrap_status == BootstrapStatus.PROVISIONING

    def test_delete_tenant(self, client, ready_worker, pending_tenant):
        response = client.delete(
            reverse(
                "worker-tenant-detail",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert response.status_code == 204
        assert not Tenant.objects.filter(id=pending_tenant.id).exists()

    def test_command_poll_updates_runtime_status(self, client, ready_worker, pending_tenant):
        provision = client.post(
            reverse(
                "worker-tenant-provision",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        command_id = provision.json()["data"]["command_id"]
        stored = AgentCommand.objects.get(id=command_id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )

        response = client.get(
            reverse(
                "worker-tenant-command-poll",
                kwargs={
                    "worker_id": ready_worker.id,
                    "tenant_id": pending_tenant.id,
                    "cmd_id": command_id,
                },
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["state"] == CommandState.ACKED
        assert body["data"]["runtime_status"] == RuntimeStatus.RUNNING

        pending_tenant.refresh_from_db()
        assert pending_tenant.runtime_status == RuntimeStatus.RUNNING

    def test_command_poll_updates_bootstrap_status(self, client, ready_worker, pending_tenant):
        bootstrap = client.post(
            reverse(
                "worker-tenant-bootstrap",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        command_id = bootstrap.json()["data"]["command_id"]
        stored = AgentCommand.objects.get(id=command_id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "api_key": "hskey-api-detail",
                    "auth_key_gateway": "hskey-gateway-detail",
                    "auth_key_workspace": "hskey-workspace-detail",
                    "admin_user_id": "admin-detail",
                    "output_ref": pending_tenant.bootstrap_output_ref,
                },
            },
        )

        response = client.get(
            reverse(
                "worker-tenant-command-poll",
                kwargs={
                    "worker_id": ready_worker.id,
                    "tenant_id": pending_tenant.id,
                    "cmd_id": command_id,
                },
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["state"] == CommandState.ACKED
        assert body["data"]["bootstrap_status"] == BootstrapStatus.BOOTSTRAPPED

        pending_tenant.refresh_from_db()
        assert pending_tenant.bootstrap_status == BootstrapStatus.BOOTSTRAPPED
        assert pending_tenant.bootstrap_secrets["api_key"] == "hskey-api-detail"

    def test_command_poll_records_health_for_verify_ack(self, client, ready_worker, pending_tenant):
        verify = client.post(
            reverse(
                "worker-tenant-verify",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        command_id = verify.json()["data"]["command_id"]
        stored = AgentCommand.objects.get(id=command_id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={"exit_code": 0, "duration_ms": 77},
        )

        response = client.get(
            reverse(
                "worker-tenant-command-poll",
                kwargs={
                    "worker_id": ready_worker.id,
                    "tenant_id": pending_tenant.id,
                    "cmd_id": command_id,
                },
            ),
        )

        assert response.status_code == 200
        health = TenantHealth.objects.filter(tenant=pending_tenant).order_by("-probed_at").first()
        assert health is not None
        assert health.healthy is True
        assert health.latency_ms == 77
        assert health.source_command_id == stored.id

        detail = client.get(
            reverse(
                "worker-tenant-detail",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )
        assert len(detail.json()["data"]["health_checks"]) == 1

    def test_provision_fails_when_worker_not_ready(self, client, ready_worker, pending_tenant):
        Worker.objects.filter(pk=ready_worker.pk).update(docker_reachable=False)

        response = client.post(
            reverse(
                "worker-tenant-provision",
                kwargs={"worker_id": ready_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert response.status_code == 400
        assert "Docker" in response.json()["error"]

    def test_tenant_not_on_worker_returns_404(self, client, ready_worker, pending_tenant):
        other_worker = Worker.objects.create(name="other-worker")
        response = client.post(
            reverse(
                "worker-tenant-provision",
                kwargs={"worker_id": other_worker.id, "tenant_id": pending_tenant.id},
            ),
        )

        assert response.status_code == 404

    def test_command_poll_not_found(self, client, ready_worker, pending_tenant):
        response = client.get(
            reverse(
                "worker-tenant-command-poll",
                kwargs={
                    "worker_id": ready_worker.id,
                    "tenant_id": pending_tenant.id,
                    "cmd_id": uuid.uuid4(),
                },
            ),
        )

        assert response.status_code == 404
