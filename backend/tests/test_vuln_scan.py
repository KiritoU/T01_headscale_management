from __future__ import annotations

import json
import subprocess

import pytest

from agent_daemon.vuln_scan import build_nuclei_targets, run_vuln_scan


class TestBuildNucleiTargets:
    def test_builds_http_and_https_urls(self) -> None:
        targets = build_nuclei_targets("192.168.1.10", [22, 80, 443, 3000])
        assert targets == [
            "http://192.168.1.10",
            "https://192.168.1.10:443",
            "http://192.168.1.10:3000",
        ]


class TestRunVulnScan:
    def test_nuclei_uses_jsonl_flag(self) -> None:
        captured: list[list[str]] = []

        def nuclei_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            captured.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout='{"template-id":"test-template","host":"192.168.1.10","ip":"192.168.1.10","matched-at":"http://192.168.1.10:3000","info":{"severity":"high","name":"Test Finding"}}\n',
                stderr="",
            )

        def nmap_runner(_command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=_command,
                returncode=0,
                stdout="192.168.1.10",
                stderr="",
            )

        original_run = subprocess.run

        def fake_run(command, **kwargs):
            if command[0].endswith("nuclei") or command[0] == "nuclei":
                return nuclei_runner(command)
            return original_run(command, **kwargs)

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "agent_daemon.vuln_scan._nuclei_installed",
                lambda: True,
            )
            monkeypatch.setattr("agent_daemon.vuln_scan.subprocess.run", fake_run)

            body = run_vuln_scan(
                ["192.168.1.10"],
                nmap_runner=nmap_runner,
                modules=["nuclei"],
                open_ports=[3000],
            )

        assert captured
        assert all("-jsonl" in command for command in captured)
        assert all("-no-stdin" in command for command in captured)
        assert "http://192.168.1.10:3000" in captured[0]
        nuclei_findings = [item for item in body["findings"] if item["source"] == "nuclei"]
        assert len(nuclei_findings) == 1
        assert nuclei_findings[0]["title"] == "Test Finding"

    def test_filters_global_matcher_false_positives(self) -> None:
        captured: list[list[str]] = []

        def nuclei_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            captured.append(command)
            stdout = "\n".join(
                [
                    json.dumps(
                        {
                            "template-id": "global-waf",
                            "host": "identity.example.com",
                            "ip": "1.2.3.4",
                            "url": "https://identity.example.com/login",
                            "info": {
                                "severity": "info",
                                "name": "Global WAF",
                                "tags": ["global-matchers"],
                            },
                        },
                    ),
                    json.dumps(
                        {
                            "template-id": "juice-shop-xss",
                            "host": "192.168.1.10",
                            "ip": "192.168.1.10",
                            "matched-at": "http://192.168.1.10:3000",
                            "info": {
                                "severity": "high",
                                "name": "Reflected XSS",
                                "tags": ["xss"],
                            },
                        },
                    ),
                ],
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=stdout,
                stderr="",
            )

        def nmap_runner(_command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=_command,
                returncode=0,
                stdout="",
                stderr="",
            )

        original_run = subprocess.run

        def fake_run(command, **kwargs):
            if "nuclei" in command[0]:
                return nuclei_runner(command)
            return original_run(command, **kwargs)

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "agent_daemon.vuln_scan._nuclei_installed",
                lambda: True,
            )
            monkeypatch.setattr("agent_daemon.vuln_scan.subprocess.run", fake_run)

            body = run_vuln_scan(
                ["192.168.1.10"],
                nmap_runner=nmap_runner,
                modules=["nuclei"],
                open_ports=[3000],
            )

        assert body["summary"]["finding_count"] == 1
        assert body["findings"][0]["title"] == "Reflected XSS"

    def test_web_audit_reports_missing_security_headers(self, monkeypatch) -> None:
        def fake_run(command, **kwargs):
            if command[0] != "curl":
                raise AssertionError(f"unexpected command: {command}")

            url = command[-1]
            if url.endswith("/"):
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="HTTP/1.1 200 OK\r\nServer: test\r\n\r\n",
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="HTTP/1.1 404 Not Found\r\n\r\n",
                stderr="",
            )

        monkeypatch.setattr("agent_daemon.vuln_scan.subprocess.run", fake_run)

        body = run_vuln_scan(
            ["192.168.1.10"],
            nmap_runner=lambda _cmd: subprocess.CompletedProcess(
                args=_cmd,
                returncode=0,
                stdout="",
                stderr="",
            ),
            modules=[],
            open_ports=[3000],
        )

        header_findings = [
            item for item in body["findings"] if item["source"] == "web-audit"
        ]
        assert len(header_findings) >= 2
        assert any("X-Frame-Options" in item["title"] for item in header_findings)

    def test_http_probe_detects_juice_shop(self, monkeypatch) -> None:
        def fake_run(command, **kwargs):
            url = command[-1]
            body = (
                "<title>OWASP Juice Shop</title>"
                if ":3000" in url
                else ""
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0 if body else 1,
                stdout=body,
                stderr="",
            )

        monkeypatch.setattr("agent_daemon.vuln_scan.subprocess.run", fake_run)

        body = run_vuln_scan(
            ["192.168.103.101"],
            nmap_runner=lambda _cmd: subprocess.CompletedProcess(
                args=_cmd,
                returncode=0,
                stdout="",
                stderr="",
            ),
            modules=[],
            open_ports=[3000],
        )

        assert body["summary"]["finding_count"] == 1
        assert body["findings"][0]["title"] == "OWASP Juice Shop detected"

    def test_masscan_fallback_used_when_ports_missing(self) -> None:
        def masscan_runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
            output = json.dumps(
                {
                    "ip": "192.168.1.20",
                    "ports": [{"port": 3000}],
                },
            )
            return subprocess.CompletedProcess(
                args=_args,
                returncode=0,
                stdout=output,
                stderr="",
            )

        captured: list[list[str]] = []

        def nuclei_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            captured.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="",
                stderr="",
            )

        def nmap_runner(_command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=_command,
                returncode=0,
                stdout="",
                stderr="",
            )

        original_run = subprocess.run

        def fake_run(command, **kwargs):
            if "nuclei" in command[0]:
                return nuclei_runner(command)
            return original_run(command, **kwargs)

        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "agent_daemon.vuln_scan._nuclei_installed",
                lambda: True,
            )
            monkeypatch.setattr("agent_daemon.vuln_scan.subprocess.run", fake_run)

            run_vuln_scan(
                ["192.168.1.20"],
                nmap_runner=nmap_runner,
                modules=["nuclei"],
                masscan_runner=masscan_runner,
            )

        assert captured
        assert "http://192.168.1.20:3000" in captured[0]
