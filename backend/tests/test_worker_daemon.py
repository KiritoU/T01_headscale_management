from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agent_daemon.client import AgentClient
from agent_daemon.stack_provisioner import ProvisionResult, TenantRuntimeResult
from agent_daemon.tenant_lifecycle import BootstrapResult, VerifyResult
from agent_daemon.worker_daemon import WorkerDaemon, main, parse_args

BASE_URL = "https://control.example.com"
AGENT_ID = "11111111-2222-3333-4444-555555555555"
TOKEN = "agnt_test_token"


def _minimal_provision_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_slug": "team-a",
        "db_name": "hs_team_a",
        "headscale_config": {"database": {"postgres": {"name": "hs_team_a"}}},
        "headplane_config": {"server": {"host": "0.0.0.0"}},
        "compose_snippet": "  headscale-team-a:\n    image: headscale/headscale:latest",
    }
    payload.update(overrides)
    return payload


def _auth_header(request: httpx.Request) -> str | None:
    return request.headers.get("Authorization")


class MockAgentServer:
    def __init__(self) -> None:
        self.heartbeats: list[dict[str, Any]] = []
        self.acks: list[dict[str, Any]] = []
        self.poll_count = 0
        self.commands: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert _auth_header(request) == f"Bearer {TOKEN}"

        if request.method == "POST" and request.url.path == "/api/v1/agents/register/":
            body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "agent_id": AGENT_ID,
                    "token": TOKEN,
                    "poll_interval_seconds": 15,
                    "name": body["name"],
                },
            )

        if request.method == "POST" and request.url.path.endswith("/heartbeat/"):
            assert request.url.path == f"/api/v1/agents/{AGENT_ID}/heartbeat/"
            self.heartbeats.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"ok": True, "poll_interval_seconds": 15})

        if request.method == "GET" and request.url.path.endswith("/poll/"):
            assert request.url.path == f"/api/v1/agents/{AGENT_ID}/poll/"
            self.poll_count += 1
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

        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def mock_server() -> MockAgentServer:
    return MockAgentServer()


@pytest.fixture
def agent_client(mock_server: MockAgentServer) -> AgentClient:
    transport = httpx.MockTransport(mock_server.handler)
    http_client = httpx.Client(transport=transport, base_url=BASE_URL)
    return AgentClient(
        control_plane_url=BASE_URL,
        token=TOKEN,
        agent_id=AGENT_ID,
        http_client=http_client,
    )


class TestAgentClient:
    def test_register_sets_agent_id(self, mock_server: MockAgentServer) -> None:
        transport = httpx.MockTransport(mock_server.handler)
        http_client = httpx.Client(transport=transport, base_url=BASE_URL)
        client = AgentClient(control_plane_url=BASE_URL, token=TOKEN, http_client=http_client)

        data = client.register(name="worker-east")

        assert data["agent_id"] == AGENT_ID
        assert client.agent_id == AGENT_ID

    def test_heartbeat_posts_payload(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
    ) -> None:
        payload = {
            "installed_modules": ["docker"],
            "docker_reachable": True,
            "tenant_inventory": ["tenant-a"],
        }

        response = agent_client.heartbeat(payload)

        assert response["ok"] is True
        assert mock_server.heartbeats == [payload]

    def test_poll_returns_commands(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
    ) -> None:
        mock_server.commands = [
            {
                "id": "cmd-1",
                "command": "verify_tenant",
                "payload": {"tenant_slug": "tenant-a"},
            }
        ]

        response = agent_client.poll()

        assert response["commands"][0]["command"] == "verify_tenant"
        assert mock_server.poll_count == 1

    def test_ack_posts_result(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
    ) -> None:
        result = {"exit_code": 0, "duration_ms": 10, "logs": "ok"}

        response = agent_client.ack("cmd-1", state="acked", result=result)

        assert response["ok"] is True
        assert mock_server.acks == [{"command_id": "cmd-1", "state": "acked", "result": result}]


class TestWorkerDaemon:
    def test_run_once_probes_docker_before_heartbeat(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.heartbeats[0]["docker_reachable"] is True

    def test_run_once_heartbeats_and_polls(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert len(mock_server.heartbeats) == 1
        assert mock_server.poll_count == 1
        assert mock_server.heartbeats[0]["docker_reachable"] is False

    def test_verify_tenant_uses_lifecycle_runner(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verify_calls: list[dict[str, Any]] = []

        class FakeLifecycleRunner:
            def verify(self, payload: dict[str, Any]) -> VerifyResult:
                verify_calls.append(payload)
                return VerifyResult(
                    exit_code=0,
                    duration_ms=150,
                    logs="verify_tenant: all checks passed for tenant-a",
                    checks={
                        "headscale_container": {
                            "name": "headscale-tenant-a",
                            "running": True,
                        },
                        "headplane_container": {
                            "name": "headplane-tenant-a",
                            "running": True,
                        },
                        "headscale_version": "0.23.0",
                        "headplane_healthy": True,
                    },
                )

        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-verify",
                "command": "verify_tenant",
                "payload": {"tenant_slug": "tenant-a"},
            }
        ]
        daemon = WorkerDaemon(agent_client, lifecycle_runner=FakeLifecycleRunner())

        daemon.run_once()

        assert len(verify_calls) == 1
        assert verify_calls[0]["tenant_slug"] == "tenant-a"
        assert mock_server.acks[0]["state"] == "acked"
        result = mock_server.acks[0]["result"]
        assert result["exit_code"] == 0
        assert result["checks"]["headscale_container"]["running"] is True
        assert result["checks"]["headplane_healthy"] is True

    def test_verify_tenant_fails_when_docker_unreachable(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [
            {
                "id": "cmd-verify-docker",
                "command": "verify_tenant",
                "payload": {"tenant_slug": "tenant-a"},
            }
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "failed"
        assert "docker is not reachable" in mock_server.acks[0]["result"]["logs"]

    def test_provision_tenant_uses_stack_provisioner(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provision_calls: list[dict[str, Any]] = []

        class FakeProvisioner:
            def provision(self, payload: dict[str, Any]) -> ProvisionResult:
                provision_calls.append(payload)
                return ProvisionResult(
                    exit_code=0,
                    duration_ms=42,
                    logs="provisioned team-a",
                    runtime_status="running",
                    config_ref="/opt/headscale-worker-stack/tenants/team-a",
                )

        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-provision",
                "command": "provision_tenant",
                "payload": _minimal_provision_payload(),
            }
        ]
        daemon = WorkerDaemon(agent_client, stack_provisioner=FakeProvisioner())

        daemon.run_once()

        assert len(provision_calls) == 1
        assert provision_calls[0]["tenant_slug"] == "team-a"
        assert mock_server.acks[0]["state"] == "acked"
        result = mock_server.acks[0]["result"]
        assert result["exit_code"] == 0
        assert result["runtime_status"] == "running"
        assert result["config_ref"] == "/opt/headscale-worker-stack/tenants/team-a"
        assert "team-a" in daemon.state.tenant_inventory

    def test_provision_tenant_fails_without_compose_snippet(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-provision-missing",
                "command": "provision_tenant",
                "payload": {"tenant_slug": "team-a"},
            }
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "failed"
        assert "missing required fields" in mock_server.acks[0]["result"]["logs"]
        assert "compose_snippet" in mock_server.acks[0]["result"]["logs"]

    def test_stop_tenant_runs_compose_stop(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stop_calls: list[str] = []

        class FakeProvisioner:
            def stop_tenant(self, tenant_slug: str) -> TenantRuntimeResult:
                stop_calls.append(tenant_slug)
                return TenantRuntimeResult(
                    exit_code=0,
                    duration_ms=500,
                    logs="stopped",
                    runtime_status="stopped",
                )

        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-stop",
                "command": "stop_tenant",
                "payload": {"tenant_slug": "team-1"},
            }
        ]
        daemon = WorkerDaemon(
            agent_client,
            stack_provisioner=FakeProvisioner(),
        )
        daemon._state = daemon.state.__class__(
            installed_modules=daemon.state.installed_modules,
            docker_reachable=True,
            tenant_inventory=("team-1", "team-2"),
        )

        daemon.run_once()

        assert stop_calls == ["team-1"]
        assert mock_server.acks[0]["state"] == "acked"
        assert mock_server.acks[0]["result"]["runtime_status"] == "stopped"
        assert "team-1" not in daemon.state.tenant_inventory

    def test_deprovision_tenant_runs_stack_deprovision(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        deprovision_calls: list[tuple[str, str]] = []

        class FakeProvisioner:
            def deprovision(
                self,
                tenant_slug: str,
                *,
                db_name: str,
                shared_edge_docker_network: str = "",
            ) -> TenantRuntimeResult:
                deprovision_calls.append((tenant_slug, db_name))
                return TenantRuntimeResult(
                    exit_code=0,
                    duration_ms=500,
                    logs="deprovisioned",
                    runtime_status="deprovisioned",
                )

        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-deprovision",
                "command": "deprovision_tenant",
                "payload": {
                    "tenant_slug": "team-1",
                    "db_name": "hs_team_1",
                },
            }
        ]
        daemon = WorkerDaemon(
            agent_client,
            stack_provisioner=FakeProvisioner(),
        )
        daemon._state = daemon.state.__class__(
            installed_modules=daemon.state.installed_modules,
            docker_reachable=True,
            tenant_inventory=("team-1", "team-2"),
        )

        daemon.run_once()

        assert deprovision_calls == [("team-1", "hs_team_1")]
        assert mock_server.acks[0]["state"] == "acked"
        assert mock_server.acks[0]["result"]["runtime_status"] == "deprovisioned"
        assert "team-1" not in daemon.state.tenant_inventory

    def test_provision_tenant_fails_when_docker_unreachable(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [
            {
                "id": "cmd-provision-docker",
                "command": "provision_tenant",
                "payload": _minimal_provision_payload(),
            }
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "failed"
        assert "docker is not reachable" in mock_server.acks[0]["result"]["logs"]

    def test_bootstrap_tenant_uses_lifecycle_runner(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bootstrap_calls: list[dict[str, Any]] = []

        class FakeLifecycleRunner:
            def bootstrap(self, payload: dict[str, Any]) -> BootstrapResult:
                bootstrap_calls.append(payload)
                return BootstrapResult(
                    exit_code=0,
                    duration_ms=2500,
                    logs="bootstrap_tenant: completed for tenant-b",
                    bootstrap_status="bootstrapped",
                    bootstrap={
                        "api_key": "hskey-api-tenant-b",
                        "auth_key_gateway": "hskey-gateway-tenant-b",
                        "auth_key_workspace": "hskey-workspace-tenant-b",
                        "admin_user_id": "1",
                        "output_ref": payload["output_ref"],
                    },
                )

        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: True,
        )
        mock_server.commands = [
            {
                "id": "cmd-bootstrap",
                "command": "bootstrap_tenant",
                "payload": {
                    "tenant_slug": "tenant-b",
                    "output_ref": "worker-output://w1/tenants/tenant-b/bootstrap",
                },
            }
        ]
        daemon = WorkerDaemon(agent_client, lifecycle_runner=FakeLifecycleRunner())

        daemon.run_once()

        assert len(bootstrap_calls) == 1
        assert bootstrap_calls[0]["tenant_slug"] == "tenant-b"
        assert mock_server.acks[0]["state"] == "acked"
        result = mock_server.acks[0]["result"]
        assert result["exit_code"] == 0
        assert result["bootstrap_status"] == "bootstrapped"
        assert result["bootstrap"]["output_ref"] == (
            "worker-output://w1/tenants/tenant-b/bootstrap"
        )
        assert result["bootstrap"]["api_key"] == "hskey-api-tenant-b"
        assert result["bootstrap"]["auth_key_gateway"] == "hskey-gateway-tenant-b"

    def test_bootstrap_tenant_fails_when_docker_unreachable(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [
            {
                "id": "cmd-bootstrap-docker",
                "command": "bootstrap_tenant",
                "payload": {"tenant_slug": "tenant-b"},
            }
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "failed"
        assert mock_server.acks[0]["result"]["bootstrap_status"] == "failed"
        assert "docker is not reachable" in mock_server.acks[0]["result"]["logs"]

    def test_install_module_marks_installed(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )

        def fake_install() -> object:
            from unittest.mock import MagicMock

            return MagicMock(returncode=0, stdout="ok", stderr="")

        mock_server.commands = [
            {
                "id": "cmd-install",
                "command": "install_module",
                "payload": {"module": "docker"},
            }
        ]
        daemon = WorkerDaemon(
            agent_client,
            docker_install_runner=fake_install,
        )

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "acked"
        assert daemon.state.installed_modules == frozenset({"docker"})
        assert mock_server.heartbeats[0]["installed_modules"] == []

        mock_server.commands = []
        daemon.run_once()
        assert mock_server.heartbeats[1]["installed_modules"] == [
            {"module_id": "docker", "status": "installed"},
        ]

    def test_install_non_docker_module_stub(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [
            {
                "id": "cmd-compose",
                "command": "install_module",
                "payload": {"module": "compose"},
            }
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "acked"
        assert daemon.state.installed_modules == frozenset({"compose"})

    def test_shutdown_command_acks_and_requests_exit(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [
            {"id": "cmd-shutdown", "command": "shutdown", "payload": {}},
        ]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "acked"
        assert daemon.shutdown_requested is True

    def test_run_forever_exits_after_shutdown(
        self,
        agent_client: AgentClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )

        class ShutdownServer(MockAgentServer):
            def handler(self, request: httpx.Request) -> httpx.Response:
                if request.method == "GET" and request.url.path.endswith("/poll/"):
                    self.commands = [{"id": "cmd-shutdown", "command": "shutdown", "payload": {}}]
                return super().handler(request)

        transport = httpx.MockTransport(ShutdownServer().handler)
        http_client = httpx.Client(transport=transport, base_url=BASE_URL)
        client = AgentClient(
            control_plane_url=BASE_URL,
            token=TOKEN,
            agent_id=AGENT_ID,
            http_client=http_client,
        )
        daemon = WorkerDaemon(client, poll_interval_seconds=15, sleep_fn=lambda _: None)

        with pytest.raises(SystemExit) as exc_info:
            daemon.run_forever()

        assert exc_info.value.code == 0

    def test_unknown_command_fails(
        self,
        agent_client: AgentClient,
        mock_server: MockAgentServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        mock_server.commands = [{"id": "cmd-unknown", "command": "restart_universe", "payload": {}}]
        daemon = WorkerDaemon(agent_client)

        daemon.run_once()

        assert mock_server.acks[0]["state"] == "failed"
        assert "unknown command" in mock_server.acks[0]["result"]["logs"]

    def test_run_forever_respects_poll_interval(
        self,
        agent_client: AgentClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "agent_daemon.worker_daemon.probe_docker_reachable",
            lambda: False,
        )
        sleeps: list[float] = []

        def sleep_and_stop(seconds: float) -> None:
            sleeps.append(seconds)
            raise KeyboardInterrupt

        daemon = WorkerDaemon(agent_client, poll_interval_seconds=15, sleep_fn=sleep_and_stop)

        with pytest.raises(KeyboardInterrupt):
            daemon.run_forever()

        assert sleeps == [15]


class TestWorkerDaemonCli:
    def test_parse_args_reads_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTROL_PLANE_URL", "https://cp.example.com")
        monkeypatch.setenv("AGENT_TOKEN", "agnt_env")
        monkeypatch.setenv("AGENT_ID", AGENT_ID)

        args = parse_args([])

        assert args.control_plane == "https://cp.example.com"
        assert args.token == "agnt_env"
        assert args.agent_id == AGENT_ID

    def test_main_requires_credentials(self) -> None:
        assert main(["--control-plane", "", "--token", ""]) == 1

    def test_main_requires_agent_id(self) -> None:
        assert main(["--control-plane", BASE_URL, "--token", TOKEN]) == 1
