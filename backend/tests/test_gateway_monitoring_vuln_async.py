from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agents.models import AgentCommand, AgentModule, CommandState
from gateways.models import (
    DiscoveredHost,
    GatewayMonitorPolicy,
    GatewayStatus,
    VulnFinding,
)
from gateways.monitoring_service import (
    get_vuln_scan_queue,
    process_monitor_scan_ack,
    process_vuln_results_push,
)
from gateways.services import create_enrollment_token, register_gateway_from_token
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker():
    return Worker.objects.create(name="vuln-worker", hostname="vuln.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-vuln",
        headscale_host="hs-vuln.example.com",
        headplane_host="hp-vuln.example.com",
        db_name="hs_team_vuln",
        worker=worker,
    )


@pytest.fixture
def enrollment_credentials(tenant):
    return create_enrollment_token(tenant, max_uses=3)


def _auth_header(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _install_vuln_modules(agent) -> None:
    now = timezone.now()
    for name in ("masscan", "nmap", "vuln-nse-pack", "iot-probes"):
        AgentModule.objects.create(agent=agent, name=name, installed_at=now)


@pytest.fixture
def vuln_gateway(enrollment_credentials):
    gateway, agent, token = register_gateway_from_token(
        enrollment_credentials.raw_token,
        hostname="vuln-gw",
    )
    gateway.status = GatewayStatus.ONLINE
    gateway.save(update_fields=["status"])
    _install_vuln_modules(agent)
    GatewayMonitorPolicy.objects.create(
        gateway=gateway,
        enabled=True,
        vuln_scan_enabled=True,
        vuln_parallel_workers=2,
    )
    return gateway, agent, token


def _monitor_scan_logs(hosts: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "subnets": [{"cidr": "192.168.0.0/24", "hosts": hosts}],
            "summary": {"host_count": len(hosts)},
        },
    )


@pytest.mark.django_db
class TestMaybeEnqueueVulnScansAsync:
    def test_marks_new_hosts_pending_without_vuln_command(self, vuln_gateway):
        gateway, agent, _token = vuln_gateway
        command = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "monitor", "targets": ["192.168.0.0/24"]},
            state=CommandState.ACKED,
            acked_at=timezone.now(),
            result={
                "exit_code": 0,
                "logs": _monitor_scan_logs(
                    [{"ip": "192.168.0.50", "hostname": "", "mac": ""}],
                ),
            },
        )

        process_monitor_scan_ack(command)

        host = DiscoveredHost.objects.get(gateway=gateway, ip="192.168.0.50")
        assert host.vuln_scan_pending is True
        assert not AgentCommand.objects.filter(agent=agent, command="vuln_scan").exists()

    def test_marks_stale_hosts_pending(self, vuln_gateway):
        gateway, agent, _token = vuln_gateway
        stale_at = timezone.now() - timedelta(days=30)
        host = DiscoveredHost.objects.create(
            gateway=gateway,
            ip="192.168.0.60",
            hostname="",
            mac="",
            first_seen_at=stale_at,
            last_seen_at=stale_at,
            is_new=False,
            last_vuln_scan_at=stale_at,
        )
        command = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "monitor", "targets": ["192.168.0.0/24"]},
            state=CommandState.ACKED,
            acked_at=timezone.now(),
            result={
                "exit_code": 0,
                "logs": _monitor_scan_logs(
                    [{"ip": "192.168.0.60", "hostname": "", "mac": ""}],
                ),
            },
        )

        process_monitor_scan_ack(command)

        host.refresh_from_db()
        assert host.vuln_scan_pending is True


@pytest.mark.django_db
class TestGetVulnScanQueue:
    def test_returns_pending_targets_capped_by_parallel_workers(self, vuln_gateway):
        gateway, agent, _token = vuln_gateway
        now = timezone.now()
        for offset, ip in enumerate(["192.168.0.1", "192.168.0.2", "192.168.0.3"]):
            DiscoveredHost.objects.create(
                gateway=gateway,
                ip=ip,
                hostname="",
                mac="",
                first_seen_at=now + timedelta(seconds=offset),
                last_seen_at=now,
                vuln_scan_pending=True,
            )

        queue = get_vuln_scan_queue(agent)

        assert queue["parallel_workers"] == 2
        assert len(queue["targets"]) == 2
        assert queue["targets"][0]["ip"] == "192.168.0.1"
        assert queue["targets"][0]["job_id"]
        assert "nmap" in queue["targets"][0]["modules"]

    def test_returns_empty_when_vuln_scan_disabled(self, enrollment_credentials):
        gateway, agent, _token = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="no-vuln-gw",
        )
        GatewayMonitorPolicy.objects.create(gateway=gateway, vuln_scan_enabled=False)

        queue = get_vuln_scan_queue(agent)

        assert queue["targets"] == []


@pytest.mark.django_db
class TestProcessVulnResultsPush:
    def test_stores_findings_and_clears_pending(self, vuln_gateway):
        gateway, agent, _token = vuln_gateway
        now = timezone.now()
        host = DiscoveredHost.objects.create(
            gateway=gateway,
            ip="192.168.0.70",
            hostname="",
            mac="",
            first_seen_at=now,
            last_seen_at=now,
            vuln_scan_pending=True,
        )

        process_vuln_results_push(
            agent,
            {
                "job_id": str(host.id),
                "ip": host.ip,
                "findings": [
                    {
                        "ip": host.ip,
                        "source": "nmap-nse",
                        "severity": "high",
                        "title": "Open SSH",
                        "finding_id": "ssh-open",
                        "details": {"port": 22},
                    },
                ],
                "completed": True,
            },
        )

        host.refresh_from_db()
        assert host.vuln_scan_pending is False
        assert host.last_vuln_scan_at is not None
        finding = VulnFinding.objects.get(discovered_host=host)
        assert finding.title == "Open SSH"
        assert finding.severity == "high"

    def test_api_endpoint_accepts_results(self, vuln_gateway):
        gateway, agent, token = vuln_gateway
        now = timezone.now()
        host = DiscoveredHost.objects.create(
            gateway=gateway,
            ip="192.168.0.80",
            hostname="",
            mac="",
            first_seen_at=now,
            last_seen_at=now,
            vuln_scan_pending=True,
        )
        client = APIClient()
        response = client.post(
            reverse("agent-vuln-results", kwargs={"agent_id": agent.id}),
            data={
                "job_id": str(host.id),
                "ip": host.ip,
                "findings": [],
                "completed": True,
            },
            format="json",
            **_auth_header(token),
        )

        assert response.status_code == 200
        host.refresh_from_db()
        assert host.vuln_scan_pending is False
        assert host.last_vuln_scan_at is not None
