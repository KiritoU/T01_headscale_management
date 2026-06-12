from __future__ import annotations

import subprocess

import pytest

from agent_daemon.network_scan import (
    ScanSubnetResult,
    build_scan_response,
    enrich_subnet_with_nmap,
    parse_ip_routes,
    scan_target_cidr,
    validate_cidr,
)


def _proc(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class TestValidateCidr:
    def test_accepts_valid_cidr(self) -> None:
        assert validate_cidr("192.168.0.0/24") == "192.168.0.0/24"

    def test_rejects_too_broad_prefix(self) -> None:
        with pytest.raises(ValueError, match="prefix"):
            validate_cidr("10.0.0.0/7")


class TestParseIpRoutes:
    def test_parses_connected_subnets(self) -> None:
        route_output = (
            "default via 192.168.100.1 dev eth0\n"
            "192.168.100.0/24 dev eth0 proto kernel scope link\n"
            "172.17.0.0/16 dev docker0 proto kernel scope link\n"
        )
        addr_output = (
            "2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>\n"
            "    inet 192.168.100.10/24 brd 192.168.100.255 scope global eth0\n"
        )

        def runner(args: list[str]) -> subprocess.CompletedProcess[str]:
            if args[:3] == ["ip", "-4", "route"]:
                return _proc(route_output)
            return _proc(addr_output)

        subnets = parse_ip_routes(runner)

        assert len(subnets) == 2
        assert subnets[0].cidr == "192.168.100.0/24"
        assert subnets[0].is_local is True
        assert subnets[1].cidr == "172.17.0.0/16"
        assert subnets[1].is_local is False


class TestNmapScan:
    def test_scan_target_cidr_parses_xml(self) -> None:
        xml_output = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.0.1" addrtype="ipv4"/>
    <hostnames><hostname name="router.local"/></hostnames>
  </host>
  <host>
    <status state="up"/>
    <address addr="192.168.0.10" addrtype="ipv4"/>
    <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac"/>
  </host>
</nmaprun>
"""

        def nmap_runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
            return _proc(xml_output)

        result = scan_target_cidr(
            "192.168.0.0/24",
            nmap_runner=nmap_runner,
            local_cidrs=("192.168.100.0/24",),
        )

        assert result.live_hosts == 2
        assert result.scan_mode == "target"
        assert result.is_local is False
        assert result.hosts[0].ip == "192.168.0.1"
        assert result.hosts[0].hostname == "router.local"
        assert result.hosts[1].mac == "AA:BB:CC:DD:EE:FF"

    def test_enrich_subnet_with_nmap(self) -> None:
        xml_output = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.100.1" addrtype="ipv4"/>
  </host>
</nmaprun>
"""
        subnet = ScanSubnetResult(
            cidr="192.168.100.0/24",
            interface="eth0",
            source="ip-route",
            live_hosts=None,
            is_local=True,
        )

        enriched = enrich_subnet_with_nmap(
            subnet,
            nmap_runner=lambda _args: _proc(xml_output),
        )

        assert enriched.live_hosts == 1
        assert enriched.hosts[0].ip == "192.168.100.1"


class TestBuildScanResponse:
    def test_includes_summary(self) -> None:
        subnets = [
            ScanSubnetResult(
                cidr="192.168.100.0/24",
                interface="eth0",
                source="nmap",
                live_hosts=3,
                is_local=True,
            ),
            ScanSubnetResult(
                cidr="192.168.0.0/24",
                interface="",
                source="nmap",
                live_hosts=10,
                scan_mode="target",
                is_local=False,
            ),
        ]

        body = build_scan_response(
            subnets,
            scan_mode="target",
            targets=["192.168.0.0/24"],
            modules_used=["core", "nmap"],
            modules_missing=[],
        )

        assert body["summary"]["subnet_count"] == 2
        assert body["summary"]["total_hosts"] == 13
        assert body["summary"]["local_networks"] == 1
        assert body["summary"]["target_networks"] == 1


class TestShouldNmapSubnet:
    def test_skips_docker_interfaces(self) -> None:
        from agent_daemon.network_scan import should_nmap_subnet

        subnet = ScanSubnetResult(
            cidr="172.17.0.0/16",
            interface="docker0",
            source="ip-route",
            live_hosts=None,
        )
        assert should_nmap_subnet(subnet) is False

    def test_allows_local_slash24(self) -> None:
        from agent_daemon.network_scan import should_nmap_subnet

        subnet = ScanSubnetResult(
            cidr="192.168.100.0/24",
            interface="eth0",
            source="ip-route",
            live_hosts=None,
            is_local=True,
        )
        assert should_nmap_subnet(subnet) is True
