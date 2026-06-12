from __future__ import annotations

import ipaddress
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RouteRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
NmapRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

NMAP_SCAN_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours — generous cap for large CIDR scans
NMAP_HOST_TIMEOUT = "2s"
NMAP_MAX_RETRIES = "1"
SKIP_INTERFACE_PREFIXES = ("docker", "br-", "veth", "virbr")
MAX_NMAP_PREFIX = 24


@dataclass(frozen=True)
class ScanHost:
    ip: str
    hostname: str
    mac: str
    status: str


@dataclass(frozen=True)
class ScanSubnetResult:
    cidr: str
    interface: str
    source: str
    live_hosts: int | None
    hosts: tuple[ScanHost, ...] = ()
    scan_mode: str = "discover"
    is_local: bool = False


def validate_cidr(value: str) -> str:
    network = ipaddress.ip_network(value, strict=False)
    if network.prefixlen < 8 or network.prefixlen > 30:
        msg = f"CIDR prefix must be between /8 and /30: {value}"
        raise ValueError(msg)
    return str(network)


def parse_ip_routes(
    route_runner: RouteRunner,
    *,
    addr_runner: RouteRunner | None = None,
) -> list[ScanSubnetResult]:
    try:
        route_proc = route_runner(["ip", "-4", "route"])
    except OSError:
        return []

    local_cidrs = _local_interface_cidrs(addr_runner or route_runner)
    subnets: list[ScanSubnetResult] = []
    seen: set[str] = set()

    for line in route_proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        destination = parts[0]
        if destination == "default" or "/" not in destination:
            continue

        interface = ""
        if "dev" in parts:
            interface = parts[parts.index("dev") + 1]

        if destination in seen:
            continue
        seen.add(destination)

        subnets.append(
            ScanSubnetResult(
                cidr=destination,
                interface=interface,
                source="ip-route",
                live_hosts=None,
                scan_mode="discover",
                is_local=_cidr_overlaps_local(destination, local_cidrs),
            ),
        )

    return subnets


def scan_target_cidr(
    cidr: str,
    *,
    nmap_runner: NmapRunner,
    local_cidrs: tuple[str, ...] = (),
    interface: str = "",
) -> ScanSubnetResult:
    validated = validate_cidr(cidr)
    hosts = _run_nmap_host_discovery(validated, nmap_runner)
    return ScanSubnetResult(
        cidr=validated,
        interface=interface,
        source="nmap",
        live_hosts=len(hosts),
        hosts=hosts,
        scan_mode="target",
        is_local=_cidr_overlaps_local(validated, local_cidrs),
    )


def enrich_subnet_with_nmap(
    subnet: ScanSubnetResult,
    *,
    nmap_runner: NmapRunner,
) -> ScanSubnetResult:
    if not should_nmap_subnet(subnet):
        return subnet

    hosts = _run_nmap_host_discovery(subnet.cidr, nmap_runner)
    return ScanSubnetResult(
        cidr=subnet.cidr,
        interface=subnet.interface,
        source=subnet.source,
        live_hosts=len(hosts),
        hosts=hosts,
        scan_mode=subnet.scan_mode,
        is_local=subnet.is_local,
    )


def should_nmap_subnet(subnet: ScanSubnetResult) -> bool:
    if subnet.interface.startswith(SKIP_INTERFACE_PREFIXES):
        return False

    try:
        network = ipaddress.ip_network(subnet.cidr, strict=False)
    except ValueError:
        return False

    if network.prefixlen < MAX_NMAP_PREFIX:
        return False

    if network.is_loopback or network.is_link_local:
        return False

    return True


def build_scan_response(
    subnets: list[ScanSubnetResult],
    *,
    scan_mode: str,
    targets: list[str],
    modules_used: list[str],
    modules_missing: list[str],
) -> dict[str, Any]:
    serialized_subnets = [subnet_to_dict(subnet) for subnet in subnets]
    total_hosts = sum(
        subnet.live_hosts or 0
        for subnet in subnets
        if subnet.live_hosts is not None
    )
    return {
        "scan_mode": scan_mode,
        "targets": targets,
        "subnets": serialized_subnets,
        "summary": {
            "subnet_count": len(serialized_subnets),
            "total_hosts": total_hosts,
            "local_networks": sum(1 for subnet in subnets if subnet.is_local),
            "target_networks": sum(1 for subnet in subnets if not subnet.is_local),
        },
        "modules_used": modules_used,
        "modules_missing": modules_missing,
    }


def subnet_to_dict(subnet: ScanSubnetResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cidr": subnet.cidr,
        "interface": subnet.interface,
        "source": subnet.source,
        "live_hosts": subnet.live_hosts,
        "scan_mode": subnet.scan_mode,
        "is_local": subnet.is_local,
    }
    if subnet.hosts:
        payload["hosts"] = [
            {
                "ip": host.ip,
                "hostname": host.hostname,
                "mac": host.mac,
                "status": host.status,
            }
            for host in subnet.hosts
        ]
    return payload


def _local_interface_cidrs(runner: RouteRunner) -> list[str]:
    cidrs: list[str] = []
    try:
        proc = runner(["ip", "-4", "addr", "show"])
    except OSError:
        return cidrs

    current_interface = ""
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\d+:", stripped):
            current_interface = stripped.split(":")[1].strip().split("@")[0]
            continue
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", stripped)
        if not match:
            continue
        ip_addr = match.group(1)
        prefix = int(match.group(2))
        network = ipaddress.ip_network(f"{ip_addr}/{prefix}", strict=False)
        cidrs.append(str(network))

    return cidrs


def _cidr_overlaps_local(cidr: str, local_cidrs: list[str] | tuple[str, ...]) -> bool:
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False

    for local in local_cidrs:
        try:
            if network.overlaps(ipaddress.ip_network(local, strict=False)):
                return True
        except ValueError:
            continue
    return False


def nmap_host_discovery_args(cidr: str) -> list[str]:
    return [
        "nmap",
        "-sn",
        "-oX",
        "-",
        "-T4",
        "--max-retries",
        NMAP_MAX_RETRIES,
        "--host-timeout",
        NMAP_HOST_TIMEOUT,
        cidr,
    ]


def _run_nmap_host_discovery(cidr: str, nmap_runner: NmapRunner) -> tuple[ScanHost, ...]:
    try:
        proc = nmap_runner(nmap_host_discovery_args(cidr))
    except subprocess.TimeoutExpired:
        return ()
    except OSError:
        return ()

    if proc.returncode != 0:
        return _parse_nmap_text_output(proc.stdout + proc.stderr)

    return _parse_nmap_xml(proc.stdout)


def _parse_nmap_xml(xml_output: str) -> tuple[ScanHost, ...]:
    if not xml_output.strip():
        return ()

    try:
        root = ET.fromstring(xml_output)
    except ET.ParseError:
        return ()

    hosts: list[ScanHost] = []
    for host in root.findall("host"):
        status = host.find("status")
        if status is not None and status.get("state") != "up":
            continue

        ip = ""
        hostname = ""
        mac = ""
        for address in host.findall("address"):
            addr_type = address.get("addrtype", "")
            if addr_type == "ipv4":
                ip = address.get("addr", "")
            elif addr_type == "mac":
                mac = address.get("addr", "")

        hostnames = host.find("hostnames")
        if hostnames is not None:
            hostname_el = hostnames.find("hostname")
            if hostname_el is not None:
                hostname = hostname_el.get("name", "")

        if ip:
            hosts.append(
                ScanHost(
                    ip=ip,
                    hostname=hostname,
                    mac=mac,
                    status="up",
                ),
            )

    return tuple(hosts)


def _parse_nmap_text_output(output: str) -> tuple[ScanHost, ...]:
    hosts: list[ScanHost] = []
    current_ip = ""

    for line in output.splitlines():
        report_match = re.search(r"Nmap scan report for (.+)", line)
        if report_match:
            target = report_match.group(1).strip()
            if "(" in target and ")" in target:
                current_ip = target.split("(")[1].rstrip(")")
            else:
                current_ip = target
            continue

        if "Host is up" in line and current_ip:
            hosts.append(
                ScanHost(ip=current_ip, hostname="", mac="", status="up"),
            )
            current_ip = ""

    return tuple(hosts)
