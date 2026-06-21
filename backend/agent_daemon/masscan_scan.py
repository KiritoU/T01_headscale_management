from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from agent_daemon.network_scan import ScanHost

MasscanRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

MASSCAN_MODULE = "masscan"
MASSCAN_SCAN_TIMEOUT_SECONDS = 120
DEFAULT_PORTS = (
    "1,22,80,443,3000,5000,8000,8080,8081,8443,8888,9000,53,445,3389"
)
DEFAULT_RATE = "10000"


def masscan_discovery_args(cidr: str, *, ports: str = DEFAULT_PORTS) -> list[str]:
    return [
        "masscan",
        cidr,
        "-p",
        ports,
        "--rate",
        DEFAULT_RATE,
        "-oJ",
        "-",
    ]


def masscan_host_args(ip: str, *, ports: str = DEFAULT_PORTS) -> list[str]:
    return [
        "masscan",
        ip,
        "-p",
        ports,
        "--rate",
        DEFAULT_RATE,
        "-oJ",
        "-",
    ]


def scan_cidr_masscan(
    cidr: str,
    *,
    masscan_runner: MasscanRunner,
) -> tuple[ScanHost, ...]:
    try:
        proc = masscan_runner(masscan_discovery_args(cidr))
    except subprocess.TimeoutExpired:
        return ()
    except OSError:
        return ()

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not output.strip():
        return ()

    return parse_masscan_hosts(output)


def scan_host_ports_masscan(
    ip: str,
    *,
    masscan_runner: MasscanRunner,
    ports: str = DEFAULT_PORTS,
) -> tuple[int, ...]:
    try:
        proc = masscan_runner(masscan_host_args(ip, ports=ports))
    except subprocess.TimeoutExpired:
        return ()
    except OSError:
        return ()

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and not output.strip():
        return ()

    hosts = parse_masscan_hosts(output)
    for host in hosts:
        if host.ip == ip:
            return host.open_ports
    return ()


def parse_masscan_hosts(output: str) -> tuple[ScanHost, ...]:
    ports_by_ip: dict[str, set[int]] = {}
    for line in output.splitlines():
        line = line.strip().rstrip(",")
        if not line or not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        ip = str(item.get("ip", "")).strip()
        if not ip:
            continue
        port_set = ports_by_ip.setdefault(ip, set())
        for port_item in item.get("ports") or []:
            if isinstance(port_item, dict):
                port_num = port_item.get("port")
            else:
                port_num = port_item
            if port_num is not None:
                port_set.add(int(port_num))

    return tuple(
        ScanHost(
            ip=ip,
            hostname="",
            mac="",
            status="up",
            open_ports=tuple(sorted(port_set)),
        )
        for ip, port_set in sorted(ports_by_ip.items())
    )


def _parse_masscan_json(output: str) -> tuple[ScanHost, ...]:
    return parse_masscan_hosts(output)
