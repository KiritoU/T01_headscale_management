from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from agent_daemon.gateway_daemon import GatewayDaemon
from agents.models import Agent, AgentCommand, AgentModule, AgentType, CommandState
from gateways.models import EnrollmentToken, Gateway, GatewayStatus
from gateways.services import (
    create_enrollment_token,
    enqueue_gateway_command,
    register_gateway_from_token,
    revoke_enrollment_token,
)
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker():
    return Worker.objects.create(name="gw-worker", hostname="gw.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-gw",
        headscale_host="hs.example.com",
        headplane_host="hp.example.com",
        db_name="hs_team_gw",
        worker=worker,
    )


@pytest.fixture
def enrollment_credentials(tenant):
    return create_enrollment_token(tenant, max_uses=2)


@pytest.mark.django_db
class TestEnrollmentTokenService:
    def test_create_enrollment_token_returns_raw_token(self, tenant):
        creds = create_enrollment_token(tenant, max_uses=3)

        assert creds.raw_token.startswith("enrl_")
        token = EnrollmentToken.objects.get(id=creds.token_id)
        assert token.tenant_id == tenant.id
        assert token.max_uses == 3
        assert token.uses == 0
        assert token.revoked is False
        assert token.token_hash != creds.raw_token

    def test_revoke_enrollment_token(self, enrollment_credentials):
        token = EnrollmentToken.objects.get(id=enrollment_credentials.token_id)

        revoke_enrollment_token(token)

        token.refresh_from_db()
        assert token.revoked is True

    def test_register_gateway_from_token_creates_agent_and_gateway(self, enrollment_credentials):
        gateway, agent, agent_token = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="edge-router-1",
        )

        assert str(gateway.tenant_id) == enrollment_credentials.tenant_id
        assert gateway.hostname == "edge-router-1"
        assert gateway.status == GatewayStatus.ENROLLED
        assert gateway.agent_id == agent.id
        assert agent.agent_type == AgentType.GATEWAY
        assert agent_token.startswith("agnt_")

        token = EnrollmentToken.objects.get(id=enrollment_credentials.token_id)
        assert token.uses == 1

    def test_register_rejects_revoked_token(self, enrollment_credentials):
        token = EnrollmentToken.objects.get(id=enrollment_credentials.token_id)
        revoke_enrollment_token(token)

        with pytest.raises(ValueError, match="revoked"):
            register_gateway_from_token(enrollment_credentials.raw_token)

    def test_register_rejects_expired_token(self, tenant):
        creds = create_enrollment_token(
            tenant,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        with pytest.raises(ValueError, match="expired"):
            register_gateway_from_token(creds.raw_token)

    def test_register_rejects_exhausted_token(self, enrollment_credentials):
        register_gateway_from_token(enrollment_credentials.raw_token)
        register_gateway_from_token(enrollment_credentials.raw_token)

        with pytest.raises(ValueError, match="exhausted"):
            register_gateway_from_token(enrollment_credentials.raw_token)


@pytest.mark.django_db
class TestEnrollmentTokenAPI:
    def test_create_enrollment_token(self, client, tenant):
        response = client.post(
            reverse("gateway-enrollment-token-create", kwargs={"tenant_id": tenant.id}),
            data={"max_uses": 5},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["token"].startswith("enrl_")
        assert body["data"]["prefix"]
        assert body["data"]["max_uses"] == 5
        assert EnrollmentToken.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
class TestGatewayDetailAPI:
    def test_get_gateway_detail(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="detail-gw",
        )
        AgentModule.objects.create(agent=agent, name="nmap", installed_at=timezone.now())

        response = client.get(reverse("gateway-detail", kwargs={"gateway_id": gateway.id}))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["id"] == str(gateway.id)
        assert body["data"]["hostname"] == "detail-gw"
        assert body["data"]["tenant_slug"] == "team-gw"
        assert body["data"]["installed_modules"] == ["nmap"]

    def test_get_gateway_detail_includes_scans_by_mode(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="scan-history-gw",
        )
        discover_cmd = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "duration_ms": 100,
                "logs": json.dumps(
                    {
                        "scan_mode": "discover",
                        "subnets": [
                            {
                                "cidr": "192.168.100.0/24",
                                "interface": "eth0",
                                "source": "ip-route",
                                "live_hosts": 3,
                                "scan_mode": "discover",
                                "is_local": True,
                            },
                        ],
                        "summary": {
                            "subnet_count": 1,
                            "total_hosts": 3,
                            "local_networks": 1,
                            "target_networks": 0,
                        },
                        "modules_used": ["core", "nmap"],
                        "modules_missing": [],
                    },
                ),
            },
        )
        target_cmd = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "target", "targets": ["192.168.102.0/24"]},
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "duration_ms": 3500,
                "logs": json.dumps(
                    {
                        "scan_mode": "target",
                        "targets": ["192.168.102.0/24"],
                        "subnets": [
                            {
                                "cidr": "192.168.102.0/24",
                                "interface": "",
                                "source": "nmap",
                                "live_hosts": 2,
                                "scan_mode": "target",
                                "is_local": False,
                            },
                        ],
                        "summary": {
                            "subnet_count": 1,
                            "total_hosts": 2,
                            "local_networks": 0,
                            "target_networks": 1,
                        },
                        "modules_used": ["core", "nmap"],
                        "modules_missing": [],
                    },
                ),
            },
        )

        response = client.get(reverse("gateway-detail", kwargs={"gateway_id": gateway.id}))

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["last_discover_scan"]["id"] == str(discover_cmd.id)
        assert data["last_target_scan"]["id"] == str(target_cmd.id)
        assert "192.168.100.0/24" in data["last_discover_scan"]["result"]["logs"]
        assert "192.168.102.0/24" in data["last_target_scan"]["result"]["logs"]

    def test_get_gateway_detail_not_found(self, client):
        import uuid

        response = client.get(
            reverse("gateway-detail", kwargs={"gateway_id": uuid.uuid4()}),
        )

        assert response.status_code == 404

    def test_delete_gateway_removes_record_and_agent(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="delete-gw",
        )
        gateway_id = gateway.id
        agent_id = agent.id
        AgentModule.objects.create(agent=agent, name="tailscale", installed_at=timezone.now())
        AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
        )

        response = client.delete(reverse("gateway-detail", kwargs={"gateway_id": gateway_id}))

        assert response.status_code == 204
        assert not Gateway.objects.filter(id=gateway_id).exists()
        assert not Agent.objects.filter(id=agent_id).exists()
        assert AgentCommand.objects.filter(agent_id=agent_id).count() == 0
        assert AgentModule.objects.filter(agent_id=agent_id).count() == 0

    def test_delete_gateway_not_found(self, client):
        import uuid

        response = client.delete(
            reverse("gateway-detail", kwargs={"gateway_id": uuid.uuid4()}),
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestGatewayRoutesAPI:
    def test_get_gateway_routes_stub(self, client, enrollment_credentials):
        gateway, _, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="routes-gw",
        )
        gateway.tailscale_node_id = "node-abc123"
        gateway.save(update_fields=["tailscale_node_id"])

        response = client.get(reverse("gateway-routes", kwargs={"gateway_id": gateway.id}))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "routes" in body["data"]
        routes = body["data"]["routes"]
        assert len(routes) >= 1
        route = routes[0]
        assert "cidr" in route
        assert "approved" in route
        assert "enabled" in route
        assert route["node_id"] == "node-abc123"


@pytest.mark.django_db
class TestGatewayCommandDetailAPI:
    def test_get_command_status_after_ack(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="cmd-gw",
        )
        cmd = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={},
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "duration_ms": 5,
                "logs": '{"subnets": []}',
            },
        )

        response = client.get(
            reverse(
                "gateway-command-detail",
                kwargs={"gateway_id": gateway.id, "cmd_id": cmd.id},
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["id"] == str(cmd.id)
        assert body["data"]["state"] == CommandState.ACKED
        assert body["data"]["result"]["exit_code"] == 0
        assert body["data"]["result"]["logs"] == '{"subnets": []}'

    def test_get_command_wrong_gateway_returns_404(self, client, enrollment_credentials, tenant):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="owner-gw",
        )
        other_creds = create_enrollment_token(tenant, max_uses=1)
        other_gateway, _, _ = register_gateway_from_token(
            other_creds.raw_token,
            hostname="other-gw",
        )
        cmd = AgentCommand.objects.create(agent=agent, command="scan_network", payload={})

        response = client.get(
            reverse(
                "gateway-command-detail",
                kwargs={"gateway_id": other_gateway.id, "cmd_id": cmd.id},
            ),
        )

        assert response.status_code == 404


@pytest.mark.django_db
class TestGatewayListAPI:
    def test_list_gateways_filtered_by_tenant(self, client, tenant, enrollment_credentials):
        gw1, _, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="gw-a",
        )
        other_tenant = Tenant.objects.create(
            slug="other-team",
            headscale_host="hs2.example.com",
            headplane_host="hp2.example.com",
            db_name="hs_other",
        )
        other_creds = create_enrollment_token(other_tenant)
        register_gateway_from_token(other_creds.raw_token, hostname="gw-b")

        response = client.get(
            reverse("gateway-list"),
            data={"tenant_id": str(tenant.id)},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        ids = {item["id"] for item in body["data"]}
        assert ids == {str(gw1.id)}


@pytest.mark.django_db
class TestGatewayTagsAPI:
    def test_patch_custom_tags(self, client, enrollment_credentials):
        gateway, _, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="tagged-gw",
        )

        response = client.patch(
            reverse("gateway-tags", kwargs={"gateway_id": gateway.id}),
            data={"custom_tags": ["tag:gateway", "tag:site-hanoi"]},
            content_type="application/json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["custom_tags"] == ["tag:gateway", "tag:site-hanoi"]

        gateway.refresh_from_db()
        assert gateway.custom_tags == ["tag:gateway", "tag:site-hanoi"]


@pytest.mark.django_db
class TestGatewayCommandsAPI:
    def test_enqueue_scan_network(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="scan-gw",
        )

        response = client.post(
            reverse("gateway-commands", kwargs={"gateway_id": gateway.id}),
            data={"command": "scan_network", "payload": {}},
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        cmd = AgentCommand.objects.get(id=body["data"]["id"])
        assert cmd.agent_id == agent.id
        assert cmd.command == "scan_network"
        assert cmd.state == CommandState.PENDING

    def test_tailscale_up_rejected_without_module(self, client, enrollment_credentials):
        gateway, _, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="no-ts-gw",
        )

        response = client.post(
            reverse("gateway-commands", kwargs={"gateway_id": gateway.id}),
            data={
                "command": "tailscale_up",
                "payload": {"login_server": "https://hs.example.com"},
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "tailscale" in body["error"].lower()

    def test_tailscale_up_allowed_with_module(self, client, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="ts-gw",
        )
        AgentModule.objects.create(
            agent=agent,
            name="tailscale",
            installed_at=timezone.now(),
        )

        response = client.post(
            reverse("gateway-commands", kwargs={"gateway_id": gateway.id}),
            data={
                "command": "tailscale_up",
                "payload": {
                    "login_server": "https://hs.example.com",
                    "auth_key": "tskey-auth-test",
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        cmd = AgentCommand.objects.get(id=body["data"]["id"])
        assert cmd.command == "tailscale_up"


@pytest.mark.django_db
class TestGatewayCommandService:
    def test_enqueue_gateway_command_gates_tailscale_up(self, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="svc-gw",
        )

        with pytest.raises(ValueError, match="tailscale"):
            enqueue_gateway_command(gateway, "tailscale_up", {"login_server": "https://x"})

        AgentModule.objects.create(agent=agent, name="tailscale", installed_at=timezone.now())
        cmd = enqueue_gateway_command(gateway, "tailscale_up", {"login_server": "https://x"})
        assert cmd.command == "tailscale_up"

    def test_enqueue_tailscale_up_includes_gateway_custom_tags(self, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="tags-gw",
        )
        Gateway.objects.filter(pk=gateway.pk).update(
            custom_tags=["tag:gateway", "tag:site-hanoi"],
        )
        gateway.refresh_from_db()
        AgentModule.objects.create(agent=agent, name="tailscale", installed_at=timezone.now())

        cmd = enqueue_gateway_command(gateway, "tailscale_up", {"login_server": "https://x"})

        assert cmd.payload["custom_tags"] == ["tag:gateway", "tag:site-hanoi"]


class MockGatewayServer:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.heartbeats: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/heartbeat/"):
            self.heartbeats.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"ok": True})

        if request.method == "GET" and request.url.path.endswith("/poll/"):
            commands = self.commands
            self.commands = []
            return httpx.Response(200, json={"commands": commands})

        is_ack = (
            request.method == "POST"
            and "/commands/" in request.url.path
            and request.url.path.endswith("/ack/")
        )
        if is_ack:
            command_id = request.url.path.split("/commands/")[1].removesuffix("/ack/")
            ack_body = json.loads(request.content.decode())
            self.acks.append({"command_id": command_id, **ack_body})
            return httpx.Response(200, json={"ok": True})

        if request.method == "GET" and request.url.path.endswith("/monitoring/vuln-queue/"):
            return httpx.Response(200, json={"parallel_workers": 4, "targets": []})

        if request.method == "POST" and request.url.path.endswith("/monitoring/vuln-results/"):
            return httpx.Response(200, json={"ok": True})

        return httpx.Response(404, json={"error": "not found"})


class TestGatewayDaemon:
    @staticmethod
    def _mock_tailscale_runner(_args: list[str]) -> type:
        return type(
            "Proc",
            (),
            {
                "stdout": json.dumps({"BackendState": "Running", "Self": {"Online": True}}),
                "stderr": "",
                "returncode": 0,
            },
        )()

    @staticmethod
    def _mock_module_install_runner(_args: list[str]) -> type:
        return type("Proc", (), {"stdout": "installed", "stderr": "", "returncode": 0})()

    def test_scan_network_stub(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        server.commands = [
            {"id": "cmd-scan", "command": "scan_network", "payload": {}},
        ]
        daemon = GatewayDaemon(client)

        daemon.run_once()

        assert server.acks[0]["state"] == "acked"
        assert "subnets" in server.acks[0]["result"]["logs"]

    def test_scan_network_sets_live_hosts_with_nmap(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        route_output = "192.168.1.0/24 dev eth0 proto kernel scope link\n"
        nmap_xml = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/><address addr="192.168.1.1" addrtype="ipv4"/></host>
  <host><status state="up"/><address addr="192.168.1.10" addrtype="ipv4"/></host>
</nmaprun>
"""

        def route_runner(args: list[str]) -> type:
            if args[:3] == ["ip", "-4", "route"]:
                return type("Proc", (), {"stdout": route_output, "returncode": 0})()
            return type("Proc", (), {"stdout": "", "returncode": 0})()

        def nmap_runner(_args: list[str]) -> type:
            return type("Proc", (), {"stdout": nmap_xml, "returncode": 0})()

        daemon = GatewayDaemon(
            client,
            route_runner=route_runner,
            nmap_runner=nmap_runner,
        )
        daemon._state = type(daemon.state)(
            installed_modules=frozenset({"core", "nmap"}),
        )
        server.commands = [{"id": "cmd-scan", "command": "scan_network", "payload": {}}]

        daemon.run_once()

        body = json.loads(server.acks[0]["result"]["logs"])
        assert body["subnets"]
        assert body["subnets"][0]["live_hosts"] == 2
        assert len(body["subnets"][0]["hosts"]) == 2

    def test_scan_network_target_mode_requires_masscan(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        daemon = GatewayDaemon(client)
        server.commands = [
            {
                "id": "cmd-scan",
                "command": "scan_network",
                "payload": {"mode": "target", "targets": ["192.168.0.0/24"]},
            },
        ]

        daemon.run_once()

        assert server.acks[0]["state"] == "failed"
        assert "masscan module" in server.acks[0]["result"]["logs"]

    def test_scan_network_target_mode_with_nmap(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        nmap_xml = """<?xml version="1.0"?>
<nmaprun>
  <host><status state="up"/><address addr="192.168.0.1" addrtype="ipv4"/></host>
</nmaprun>
"""

        def route_runner(args: list[str]) -> type:
            if args[:3] == ["ip", "-4", "route"]:
                return type(
                    "Proc",
                    (),
                    {"stdout": "192.168.100.0/24 dev eth0 proto kernel scope link\n", "returncode": 0},
                )()
            return type("Proc", (), {"stdout": "", "returncode": 0})()

        daemon = GatewayDaemon(
            client,
            route_runner=route_runner,
            nmap_runner=lambda _args: type("Proc", (), {"stdout": nmap_xml, "returncode": 0})(),
        )
        daemon._state = type(daemon.state)(installed_modules=frozenset({"core", "nmap"}))
        server.commands = [
            {
                "id": "cmd-scan",
                "command": "scan_network",
                "payload": {"mode": "target", "targets": ["192.168.0.0/24"]},
            },
        ]

        daemon.run_once()

        body = json.loads(server.acks[0]["result"]["logs"])
        assert body["scan_mode"] == "target"
        assert body["subnets"][0]["cidr"] == "192.168.0.0/24"
        assert body["subnets"][0]["live_hosts"] == 1
        assert body["subnets"][0]["is_local"] is False

    def test_tailscale_up_requires_module(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        server.commands = [
            {
                "id": "cmd-ts",
                "command": "tailscale_up",
                "payload": {"login_server": "https://hs.example.com"},
            },
        ]
        daemon = GatewayDaemon(client)

        daemon.run_once()

        assert server.acks[0]["state"] == "failed"
        assert "tailscale module" in server.acks[0]["result"]["logs"]

    def test_install_module_tailscale_then_tailscale_up(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        daemon = GatewayDaemon(
            client,
            tailscale_runner=self._mock_tailscale_runner,
            module_install_runner=self._mock_module_install_runner,
        )

        server.commands = [
            {"id": "cmd-install", "command": "install_module", "payload": {"module": "tailscale"}},
        ]
        daemon.run_once()
        assert server.acks[0]["state"] == "acked"
        assert "tailscale" in daemon.state.installed_modules

        server.commands = [
            {
                "id": "cmd-ts",
                "command": "tailscale_up",
                "payload": {"login_server": "https://hs.example.com", "auth_key": "secret"},
            },
        ]
        daemon.run_once()
        assert server.acks[1]["state"] == "acked"
        result_body = json.loads(server.acks[1]["result"]["logs"])
        assert result_body["login_server"] == "https://hs.example.com"
        assert result_body["custom_tags"] == []

    def test_tailscale_up_includes_custom_tags_from_payload(self) -> None:
        agent_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        server = MockGatewayServer(agent_id)
        transport = httpx.MockTransport(server.handler)
        http_client = httpx.Client(transport=transport, base_url="https://cp.example.com")
        from agent_daemon.client import AgentClient

        client = AgentClient(
            control_plane_url="https://cp.example.com",
            token="agnt_test",
            agent_id=agent_id,
            http_client=http_client,
        )
        daemon = GatewayDaemon(client, tailscale_runner=self._mock_tailscale_runner)
        daemon._state = type(daemon.state)(installed_modules=frozenset({"core", "tailscale"}))
        server.commands = [
            {
                "id": "cmd-ts",
                "command": "tailscale_up",
                "payload": {
                    "login_server": "https://hs.example.com",
                    "custom_tags": ["tag:gateway", "tag:site-test"],
                },
            },
        ]

        daemon.run_once()

        assert server.acks[0]["state"] == "acked"
        result_body = json.loads(server.acks[0]["result"]["logs"])
        assert result_body["custom_tags"] == ["tag:gateway", "tag:site-test"]
