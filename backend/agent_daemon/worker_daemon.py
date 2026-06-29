from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_daemon.client import AgentClient
from agent_daemon.docker_probe import probe_docker_reachable
from agent_daemon.stack_provisioner import StackProvisioner
from agent_daemon.system_metrics import SystemMetricsCollector
from agent_daemon.tenant_lifecycle import TenantLifecycleRunner
from lifecycle.identifiers import validate_db_name

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 15
DOCKER_MODULE = "docker"
DOCKER_INSTALL_TIMEOUT_SECONDS = 600
DOCKER_INSTALL_SCRIPT = "curl -fsSL https://get.docker.com | sh"
_REQUIRED_PROVISION_FIELDS = (
    "tenant_slug",
    "db_name",
    "headscale_config",
    "headplane_config",
    "compose_snippet",
)


@dataclass(frozen=True)
class WorkerDaemonState:
    installed_modules: frozenset[str] = frozenset()
    docker_reachable: bool = False
    tenant_inventory: tuple[str, ...] = ()


class WorkerDaemon:
    """Poll loop that heartbeats, fetches commands, and acknowledges results.

    Architecture:
    - Docker: probe on every heartbeat via probe_docker_reachable() so transient
      daemon outages do not leave a stale false negative on the control plane.
    - Docker install is an optional module via install_module (not in enroll
      script) to keep worker enrollment fast like gateway core-only bootstrap.
    - Disconnect vs delete (control plane): disconnect revokes the agent token
      and sends shutdown; delete removes the worker record when no tenants remain.
    """

    def __init__(
        self,
        client: AgentClient,
        *,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
        docker_install_runner: Callable[[], subprocess.CompletedProcess[str]] | None = None,
        stack_provisioner: StackProvisioner | None = None,
        lifecycle_runner: TenantLifecycleRunner | None = None,
        metrics_collector: SystemMetricsCollector | None = None,
    ) -> None:
        self._client = client
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep_fn = sleep_fn
        self._docker_install_runner = docker_install_runner
        self._stack_provisioner = stack_provisioner or StackProvisioner()
        self._lifecycle_runner = lifecycle_runner or TenantLifecycleRunner()
        self._metrics_collector = metrics_collector or SystemMetricsCollector()
        self._state = WorkerDaemonState()
        self._shutdown_requested = False

    @property
    def state(self) -> WorkerDaemonState:
        return self._state

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def run_once(self) -> None:
        self._refresh_docker_reachability()
        self._client.heartbeat(self._heartbeat_payload())
        poll_response = self._client.poll()
        for command in poll_response.get("commands", []):
            self._handle_command(command)

    def run_forever(self) -> None:
        while not self._shutdown_requested:
            try:
                self.run_once()
            except Exception:
                logger.exception("worker daemon cycle failed")
            if self._shutdown_requested:
                break
            self._sleep_fn(self._poll_interval_seconds)
        raise SystemExit(0)

    def _refresh_docker_reachability(self) -> None:
        docker_reachable = probe_docker_reachable()
        self._state = WorkerDaemonState(
            installed_modules=self._state.installed_modules,
            docker_reachable=docker_reachable,
            tenant_inventory=self._state.tenant_inventory,
        )

    def _heartbeat_payload(self) -> dict[str, Any]:
        modules = [
            {"module_id": module_id, "status": "installed"}
            for module_id in sorted(self._state.installed_modules)
        ]
        return {
            "installed_modules": modules,
            "docker_reachable": self._state.docker_reachable,
            "tenant_inventory": list(self._state.tenant_inventory),
            "metrics": self._metrics_collector.sample(),
        }

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_id = command["id"]
        command_type = command["command"]
        payload = command.get("payload", {})
        try:
            result, state = self._execute_command(command_type, payload)
        except Exception as exc:
            logger.exception("command %s failed", command_type)
            result = {"exit_code": 1, "duration_ms": 0, "logs": str(exc)}
            state = "failed"
        self._client.ack(command_id, state=state, result=result)

    def _execute_command(
        self,
        command_type: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if command_type == "verify_tenant":
            return self._handle_verify_tenant(payload)
        if command_type == "bootstrap_tenant":
            return self._handle_bootstrap_tenant(payload)
        if command_type == "provision_tenant":
            return self._handle_provision_tenant(payload)
        if command_type == "start_tenant":
            return self._handle_start_tenant(payload)
        if command_type == "stop_tenant":
            return self._handle_stop_tenant(payload)
        if command_type == "deprovision_tenant":
            return self._handle_deprovision_tenant(payload)
        if command_type == "install_module":
            return self._handle_install_module(payload)
        if command_type == "shutdown":
            return self._handle_shutdown(payload)
        return (
            {
                "exit_code": 1,
                "duration_ms": 0,
                "logs": f"unknown command: {command_type}",
            },
            "failed",
        )

    def _validate_provision_payload(self, payload: dict[str, Any]) -> str | None:
        missing = [
            field
            for field in _REQUIRED_PROVISION_FIELDS
            if not payload.get(field)
        ]
        if missing:
            return (
                "provision_tenant: missing required fields: "
                + ", ".join(missing)
            )
        try:
            validate_db_name(str(payload["db_name"]))
        except ValueError as exc:
            return f"provision_tenant: {exc}"
        return None

    def _handle_shutdown(self, _payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        self._shutdown_requested = True
        return (
            {
                "exit_code": 0,
                "duration_ms": 0,
                "logs": "shutdown acknowledged",
            },
            "acked",
        )

    def _handle_verify_tenant(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not self._state.docker_reachable:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "verify_tenant: docker is not reachable",
                },
                "failed",
            )

        result = self._lifecycle_runner.verify(payload)
        state = "acked" if result.exit_code == 0 else "failed"
        return (
            {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "logs": result.logs,
                "checks": result.checks,
            },
            state,
        )

    def _handle_bootstrap_tenant(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not self._state.docker_reachable:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "bootstrap_tenant: docker is not reachable",
                    "bootstrap_status": "failed",
                },
                "failed",
            )

        result = self._lifecycle_runner.bootstrap(payload)
        state = "acked" if result.exit_code == 0 else "failed"
        response: dict[str, Any] = {
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "logs": result.logs,
            "bootstrap_status": result.bootstrap_status,
        }
        if result.bootstrap is not None:
            response["bootstrap"] = result.bootstrap
        return (response, state)

    def _handle_provision_tenant(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        tenant_slug = payload.get("tenant_slug", "unknown")
        validation_error = self._validate_provision_payload(payload)
        if validation_error is not None:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": validation_error,
                    "runtime_status": "failed",
                },
                "failed",
            )

        if not self._state.docker_reachable:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "provision_tenant: docker is not reachable",
                    "runtime_status": "failed",
                },
                "failed",
            )

        result = self._stack_provisioner.provision(payload)
        if result.exit_code == 0:
            inventory = tuple(sorted(set(self._state.tenant_inventory) | {tenant_slug}))
            self._state = WorkerDaemonState(
                installed_modules=self._state.installed_modules,
                docker_reachable=self._state.docker_reachable,
                tenant_inventory=inventory,
            )
        state = "acked" if result.exit_code == 0 else "failed"
        return (
            {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "logs": result.logs,
                "runtime_status": result.runtime_status,
                "config_ref": result.config_ref,
            },
            state,
        )

    def _handle_start_tenant(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return self._handle_tenant_runtime_action(
            payload,
            action="start_tenant",
            runner=self._stack_provisioner.start_tenant,
            inventory_on_success=lambda slug, inventory: tuple(
                sorted(set(inventory) | {slug}),
            ),
        )

    def _handle_deprovision_tenant(
        self,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        tenant_slug = str(payload.get("tenant_slug", "unknown"))
        db_name = str(payload.get("db_name", "")).strip()
        if not db_name:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "deprovision_tenant: db_name is required",
                    "runtime_status": "failed",
                },
                "failed",
            )
        try:
            validate_db_name(db_name)
        except ValueError as exc:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": f"deprovision_tenant: {exc}",
                    "runtime_status": "failed",
                },
                "failed",
            )

        if not self._state.docker_reachable:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "deprovision_tenant: docker is not reachable",
                    "runtime_status": "failed",
                },
                "failed",
            )

        result = self._stack_provisioner.deprovision(
            tenant_slug,
            db_name=db_name,
            shared_edge_docker_network=str(
                payload.get("shared_edge_docker_network", ""),
            ),
        )
        state = "acked" if result.exit_code == 0 else "failed"
        if result.exit_code == 0:
            self._state = WorkerDaemonState(
                installed_modules=self._state.installed_modules,
                docker_reachable=self._state.docker_reachable,
                tenant_inventory=tuple(
                    slug
                    for slug in self._state.tenant_inventory
                    if slug != tenant_slug
                ),
            )
        return (
            {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "logs": result.logs,
                "runtime_status": result.runtime_status,
            },
            state,
        )

    def _handle_stop_tenant(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        return self._handle_tenant_runtime_action(
            payload,
            action="stop_tenant",
            runner=self._stack_provisioner.stop_tenant,
            inventory_on_success=lambda slug, inventory: tuple(
                item for item in inventory if item != slug
            ),
        )

    def _handle_tenant_runtime_action(
        self,
        payload: dict[str, Any],
        *,
        action: str,
        runner: Callable[[str], Any],
        inventory_on_success: Callable[[str, tuple[str, ...]], tuple[str, ...]],
    ) -> tuple[dict[str, Any], str]:
        tenant_slug = str(payload.get("tenant_slug", "unknown"))
        if not self._state.docker_reachable:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": f"{action}: docker is not reachable",
                    "runtime_status": "failed",
                },
                "failed",
            )

        result = runner(tenant_slug)
        if result.exit_code == 0:
            inventory = inventory_on_success(tenant_slug, self._state.tenant_inventory)
            self._state = WorkerDaemonState(
                installed_modules=self._state.installed_modules,
                docker_reachable=self._state.docker_reachable,
                tenant_inventory=inventory,
            )
        state = "acked" if result.exit_code == 0 else "failed"
        return (
            {
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "logs": result.logs,
                "runtime_status": result.runtime_status,
            },
            state,
        )

    def _handle_install_module(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        module_name = payload.get("module")
        if not module_name:
            return (
                {"exit_code": 1, "duration_ms": 0, "logs": "missing module name"},
                "failed",
            )
        if module_name == DOCKER_MODULE:
            return self._install_docker_module()
        return self._mark_module_installed(module_name)

    def _mark_module_installed(self, module_name: str) -> tuple[dict[str, Any], str]:
        self._state = WorkerDaemonState(
            installed_modules=self._state.installed_modules | {module_name},
            docker_reachable=self._state.docker_reachable,
            tenant_inventory=self._state.tenant_inventory,
        )
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": f"installed module: {module_name}",
            },
            "acked",
        )

    def _default_docker_install_runner(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", "-c", DOCKER_INSTALL_SCRIPT],
            capture_output=True,
            text=True,
            timeout=DOCKER_INSTALL_TIMEOUT_SECONDS,
            check=False,
        )

    def _install_docker_module(self) -> tuple[dict[str, Any], str]:
        runner = self._docker_install_runner or self._default_docker_install_runner
        started = time.monotonic()
        try:
            proc = runner()
        except subprocess.TimeoutExpired:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                {
                    "exit_code": 1,
                    "duration_ms": duration_ms,
                    "logs": "docker install timed out",
                },
                "failed",
            )
        except OSError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return (
                {
                    "exit_code": 1,
                    "duration_ms": duration_ms,
                    "logs": str(exc),
                },
                "failed",
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode != 0:
            logs = (proc.stderr or proc.stdout or "docker install failed").strip()
            return (
                {
                    "exit_code": proc.returncode,
                    "duration_ms": duration_ms,
                    "logs": logs,
                },
                "failed",
            )

        docker_reachable = probe_docker_reachable()
        self._state = WorkerDaemonState(
            installed_modules=self._state.installed_modules | {DOCKER_MODULE},
            docker_reachable=docker_reachable,
            tenant_inventory=self._state.tenant_inventory,
        )
        return (
            {
                "exit_code": 0,
                "duration_ms": duration_ms,
                "logs": "installed module: docker",
            },
            "acked",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker agent daemon")
    parser.add_argument(
        "--control-plane",
        default=os.environ.get("CONTROL_PLANE_URL"),
        help="Control plane base URL (env: CONTROL_PLANE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("AGENT_TOKEN"),
        help="Agent bearer token (env: AGENT_TOKEN)",
    )
    parser.add_argument(
        "--agent-id",
        default=os.environ.get("AGENT_ID"),
        help="Registered agent UUID (env: AGENT_ID)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Seconds between poll cycles",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.control_plane or not args.token:
        print("CONTROL_PLANE_URL and AGENT_TOKEN are required", file=sys.stderr)
        return 1
    if not args.agent_id:
        print("AGENT_ID is required for polling endpoints", file=sys.stderr)
        return 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = AgentClient(
        control_plane_url=args.control_plane,
        token=args.token,
        agent_id=args.agent_id,
    )
    daemon = WorkerDaemon(client, poll_interval_seconds=args.poll_interval)
    try:
        daemon.run_forever()
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
