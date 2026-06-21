from __future__ import annotations

import subprocess

import pytest

from agent_daemon.masscan_scan import (
    masscan_discovery_args,
    scan_cidr_masscan,
)


class TestMasscanDiscoveryArgs:
    def test_builds_expected_command(self) -> None:
        args = masscan_discovery_args("192.168.0.0/24")
        assert args[:2] == ["masscan", "192.168.0.0/24"]
        assert "-p" in args
        assert "--rate" in args
        assert "-oJ" in args
        assert args[-1] == "-"


class TestScanCidrMasscan:
    def test_parses_json_lines(self) -> None:
        output = '\n'.join(
            [
                '{"ip": "192.168.0.10", "ports": [{"port": 80}]}',
                '{"ip": "192.168.0.11", "ports": [{"port": 443}]}',
            ],
        )

        def runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=_args,
                returncode=0,
                stdout=output,
                stderr="",
            )

        hosts = scan_cidr_masscan("192.168.0.0/24", masscan_runner=runner)
        assert len(hosts) == 2
        assert {host.ip for host in hosts} == {"192.168.0.10", "192.168.0.11"}
        assert hosts[0].open_ports == (80,)
        assert hosts[1].open_ports == (443,)

    def test_returns_empty_on_timeout(self) -> None:
        def runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(cmd=_args, timeout=1)

        assert scan_cidr_masscan("192.168.0.0/24", masscan_runner=runner) == ()

    def test_returns_empty_on_nonzero_exit_without_output(self) -> None:
        def runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=_args,
                returncode=1,
                stdout="",
                stderr="",
            )

        assert scan_cidr_masscan("192.168.0.0/24", masscan_runner=runner) == ()
