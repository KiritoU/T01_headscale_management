from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_daemon.client import AgentClient
from agent_daemon.masscan_scan import MASSCAN_MODULE, scan_cidr_masscan
from agent_daemon.module_installer import (
    IOT_PROBES_MODULE,
    NMAP_MODULE,
    NUCLEI_MODULE,
    SUPPORTED_MODULES,
    TAILSCALE_MODULE,
    VULN_NSE_PACK_MODULE,
    _nuclei_installed,
    install_gateway_module,
)
from agent_daemon.vuln_scan import run_vuln_scan
from agent_daemon.vuln_worker import VulnWorkerPool
from agent_daemon.network_scan import (
    ScanSubnetResult,
    _cidr_overlaps_local,
    build_scan_response,
    enrich_subnet_with_nmap,
    parse_ip_routes,
    scan_target_cidr,
    validate_cidr,
)

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 15
CORE_MODULE = "core"
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GatewayDaemonState:
    installed_modules: frozenset[str] = frozenset({CORE_MODULE})


class GatewayDaemon:
    """Poll loop for gateway agents: scan, tailscale, and module installs."""

    def __init__(
        self,
        client: AgentClient,
        *,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
        route_runner: CommandRunner | None = None,
        nmap_runner: CommandRunner | None = None,
        tailscale_runner: CommandRunner | None = None,
        module_install_runner: CommandRunner | None = None,
        masscan_runner: CommandRunner | None = None,
        auto_detect_modules: bool = False,
    ) -> None:
        self._client = client
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep_fn = sleep_fn
        self._route_runner = route_runner or self._default_command_runner
        self._nmap_runner = nmap_runner or self._default_nmap_runner
        self._tailscale_runner = tailscale_runner or self._default_command_runner
        self._module_install_runner = module_install_runner
        self._masscan_runner = masscan_runner or self._default_masscan_runner
        initial_modules = (
            _detect_installed_modules() if auto_detect_modules else frozenset({CORE_MODULE})
        )
        self._state = GatewayDaemonState(installed_modules=initial_modules)
        self._vuln_worker = VulnWorkerPool(
            client,
            nmap_runner=self._nmap_runner,
            masscan_runner=self._masscan_runner,
        )

    @property
    def state(self) -> GatewayDaemonState:
        return self._state

    def run_once(self) -> None:
        self._client.heartbeat(self._heartbeat_payload())
        poll_response = self._client.poll()
        for command in poll_response.get("commands", []):
            self._handle_command(command)
        self._vuln_worker.tick()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("gateway daemon cycle failed")
            self._sleep_fn(self._poll_interval_seconds)

    def _heartbeat_payload(self) -> dict[str, Any]:
        modules = [
            {"module_id": module_id, "status": "installed"}
            for module_id in sorted(self._state.installed_modules)
        ]
        return {"installed_modules": modules}

    def _handle_command(self, command: dict[str, Any]) -> None:
        command_id = command["id"]
        command_type = command["command"]
        payload = command.get("payload", {})
        started = time.monotonic()
        try:
            result, state = self._execute_command(command_type, payload)
        except Exception as exc:
            logger.exception("command %s failed", command_type)
            result = {
                "exit_code": 1,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "logs": str(exc),
            }
            state = "failed"
        else:
            if "duration_ms" not in result:
                result = {
                    **result,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
        self._client.ack(command_id, state=state, result=result)

    def _execute_command(
        self,
        command_type: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if command_type == "scan_network":
            return self._handle_scan_network(payload)
        if command_type == "vuln_scan":
            return self._handle_vuln_scan(payload)
        if command_type == "tailscale_up":
            return self._handle_tailscale_up(payload)
        if command_type == "tailscale_status":
            return self._handle_tailscale_status(payload)
        if command_type == "install_module":
            return self._handle_install_module(payload)
        return (
            {
                "exit_code": 1,
                "duration_ms": 0,
                "logs": f"unknown command: {command_type}",
            },
            "failed",
        )

    def _handle_scan_network(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        started = time.monotonic()
        scan_mode = payload.get("mode", "discover")
        targets = list(payload.get("targets") or [])
        has_masscan = MASSCAN_MODULE in self._state.installed_modules
        has_nmap = NMAP_MODULE in self._state.installed_modules
        modules_used = [CORE_MODULE]
        modules_missing: list[str] = []

        if scan_mode in {"target", "monitor"}:
            if not targets:
                return (
                    {
                        "exit_code": 1,
                        "duration_ms": 0,
                        "logs": "targets required for target/monitor scan mode",
                    },
                    "failed",
                )
            use_masscan = has_masscan
            if not use_masscan and not has_nmap:
                modules_missing.append(MASSCAN_MODULE)
                return (
                    {
                        "exit_code": 1,
                        "duration_ms": 0,
                        "logs": "masscan module is required for monitor/target discovery scans",
                    },
                    "failed",
                )

            local_cidrs = tuple(
                subnet.cidr
                for subnet in parse_ip_routes(self._route_runner)
            )
            subnets: list[ScanSubnetResult] = []
            for target in targets:
                try:
                    validated = validate_cidr(target)
                except ValueError as exc:
                    return (
                        {
                            "exit_code": 1,
                            "duration_ms": 0,
                            "logs": str(exc),
                        },
                        "failed",
                    )
                if use_masscan:
                    hosts = scan_cidr_masscan(
                        validated,
                        masscan_runner=self._masscan_runner,
                    )
                    subnets.append(
                        ScanSubnetResult(
                            cidr=validated,
                            interface="",
                            source="masscan",
                            live_hosts=len(hosts),
                            hosts=hosts,
                            scan_mode=scan_mode,
                            is_local=_cidr_overlaps_local(validated, local_cidrs),
                        ),
                    )
                else:
                    scanned = scan_target_cidr(
                        validated,
                        nmap_runner=self._nmap_runner,
                        local_cidrs=local_cidrs,
                    )
                    subnets.append(
                        ScanSubnetResult(
                            cidr=scanned.cidr,
                            interface=scanned.interface,
                            source=scanned.source,
                            live_hosts=scanned.live_hosts,
                            hosts=scanned.hosts,
                            scan_mode=scan_mode,
                            is_local=scanned.is_local,
                        ),
                    )
            modules_used.append(MASSCAN_MODULE if use_masscan else NMAP_MODULE)
        else:
            subnets = parse_ip_routes(self._route_runner)
            if has_nmap:
                subnets = [
                    enrich_subnet_with_nmap(subnet, nmap_runner=self._nmap_runner)
                    for subnet in subnets
                ]
                modules_used.append(NMAP_MODULE)
            else:
                modules_missing.append(NMAP_MODULE)

        body = build_scan_response(
            subnets,
            scan_mode=scan_mode,
            targets=targets,
            modules_used=modules_used,
            modules_missing=modules_missing,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return (
            {
                "exit_code": 0,
                "duration_ms": duration_ms,
                "logs": json.dumps(body),
            },
            "acked",
        )

    def _handle_tailscale_up(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if TAILSCALE_MODULE not in self._state.installed_modules:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "tailscale module is not installed",
                },
                "failed",
            )

        login_server = payload.get("login_server", "")
        auth_key = payload.get("auth_key", "")
        advertise_routes = payload.get("advertise_routes", "")
        custom_tags = list(payload.get("custom_tags") or [])
        accept_dns = payload.get("accept_dns", True)
        accept_routes = payload.get("accept_routes", False)
        force_reauth = payload.get("force_reauth", True)
        reset = payload.get("reset", True)

        if not login_server:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "login_server is required",
                },
                "failed",
            )

        command = ["tailscale", "up", f"--login-server={login_server}"]

        if auth_key:
            command.append(f"--authkey={auth_key}")
        if advertise_routes:
            command.append(f"--advertise-routes={advertise_routes}")
        if custom_tags:
            command.append(f"--advertise-tags={','.join(custom_tags)}")
        if accept_dns:
            command.append("--accept-dns")
        else:
            command.append("--accept-dns=false")
        if accept_routes is True:
            command.append("--accept-routes")
        if force_reauth:
            command.append("--force-reauth")
        if reset:
            command.append("--reset")

        proc = self._tailscale_runner(command)
        logs = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode != 0:
            return (
                {
                    "exit_code": proc.returncode,
                    "duration_ms": 1,
                    "logs": logs or "tailscale up failed",
                },
                "failed",
            )

        body = {
            "login_server": login_server,
            "custom_tags": custom_tags,
            "advertise_routes": advertise_routes,
            "status": "connected",
            "output": logs,
        }
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": json.dumps(body),
            },
            "acked",
        )

    def _handle_tailscale_status(self, _payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if TAILSCALE_MODULE not in self._state.installed_modules:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "tailscale module is not installed",
                },
                "failed",
            )

        proc = self._tailscale_runner(["tailscale", "status", "--json"])
        logs = (proc.stdout or proc.stderr or "").strip()
        if proc.returncode != 0:
            return (
                {
                    "exit_code": proc.returncode,
                    "duration_ms": 1,
                    "logs": logs or "tailscale status failed",
                },
                "failed",
            )

        try:
            status_body = json.loads(logs)
        except json.JSONDecodeError:
            status_body = {"raw": logs}

        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": json.dumps(status_body),
            },
            "acked",
        )

    def _handle_install_module(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        module_name = payload.get("module")
        if not module_name:
            return (
                {"exit_code": 1, "duration_ms": 0, "logs": "missing module name"},
                "failed",
            )
        if module_name not in SUPPORTED_MODULES:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": f"unsupported module: {module_name}",
                },
                "failed",
            )

        result, state = install_gateway_module(
            module_name,
            command_runner=self._module_install_runner,
            control_plane_url=os.environ.get("CONTROL_PLANE_URL"),
        )
        if state == "acked":
            self._state = GatewayDaemonState(
                installed_modules=self._state.installed_modules | {module_name},
            )
        return result, state

    def _handle_vuln_scan(self, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        targets = list(payload.get("targets") or [])
        modules = list(payload.get("modules") or [])
        if not targets:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "targets required for vuln_scan",
                },
                "failed",
            )
        if NMAP_MODULE not in self._state.installed_modules:
            return (
                {
                    "exit_code": 1,
                    "duration_ms": 0,
                    "logs": "nmap module is required for vuln_scan",
                },
                "failed",
            )

        body = run_vuln_scan(
            targets,
            nmap_runner=self._nmap_runner,
            modules=modules,
            masscan_runner=self._masscan_runner,
        )
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": json.dumps(body),
            },
            "acked",
        )

    def _default_command_runner(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def _default_nmap_runner(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        from agent_daemon.network_scan import NMAP_SCAN_TIMEOUT_SECONDS

        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=NMAP_SCAN_TIMEOUT_SECONDS,
        )

    def _default_masscan_runner(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        from agent_daemon.masscan_scan import MASSCAN_SCAN_TIMEOUT_SECONDS

        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=MASSCAN_SCAN_TIMEOUT_SECONDS,
        )


def _detect_installed_modules() -> frozenset[str]:
    modules = {CORE_MODULE}
    if shutil.which("tailscale"):
        modules.add(TAILSCALE_MODULE)
    if shutil.which("nmap"):
        modules.add(NMAP_MODULE)
    if shutil.which("masscan"):
        modules.add(MASSCAN_MODULE)
    if _nuclei_installed():
        modules.add(NUCLEI_MODULE)
    return frozenset(modules)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gateway agent daemon")
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
        default=int(os.environ.get("POLL_INTERVAL", DEFAULT_POLL_INTERVAL_SECONDS)),
        help="Seconds between poll cycles (env: POLL_INTERVAL)",
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
    daemon = GatewayDaemon(
        client,
        poll_interval_seconds=args.poll_interval,
        auto_detect_modules=True,
    )
    try:
        daemon.run_forever()
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
