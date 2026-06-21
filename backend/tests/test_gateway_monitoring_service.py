from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from agents.models import AgentCommand, AgentModule, CommandState
from gateways.models import (
    AlertType,
    DiscoveredHost,
    GatewayMonitorPolicy,
    GatewayStatus,
    MonitorAlert,
    ScanSnapshot,
)
from gateways.monitoring_service import process_monitor_scan_ack, run_monitor_scheduler
from gateways.services import create_enrollment_token, register_gateway_from_token
from django.urls import reverse
from rest_framework.test import APIClient
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker():
    return Worker.objects.create(name="monitor-worker", hostname="monitor.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-monitor",
        headscale_host="hs-monitor.example.com",
        headplane_host="hp-monitor.example.com",
        db_name="hs_team_monitor",
        worker=worker,
    )


@pytest.fixture
def enrollment_credentials(tenant):
    return create_enrollment_token(tenant, max_uses=3)


@pytest.fixture
def online_gateway(enrollment_credentials):
    gateway, agent, _ = register_gateway_from_token(
        enrollment_credentials.raw_token,
        hostname="monitor-gw",
    )
    gateway.status = GatewayStatus.ONLINE
    gateway.save(update_fields=["status"])
    AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())
    return gateway, agent


def _monitor_scan_logs(hosts: list[dict[str, str]], *, cidr: str = "192.168.0.0/24") -> str:
    return json.dumps(
        {
            "subnets": [{"cidr": cidr, "hosts": hosts}],
            "summary": {"host_count": len(hosts)},
        },
    )


def _create_monitor_scan_command(
    agent,
    *,
    hosts: list[dict[str, str]],
    targets: list[str] | None = None,
    state: str = CommandState.ACKED,
    mode: str = "monitor",
) -> AgentCommand:
    scanned_at = timezone.now()
    return AgentCommand.objects.create(
        agent=agent,
        command="scan_network",
        payload={
            "mode": mode,
            "targets": targets or ["192.168.0.0/24"],
        },
        state=state,
        acked_at=scanned_at if state == CommandState.ACKED else None,
        result={
            "exit_code": 0,
            "logs": _monitor_scan_logs(hosts),
        },
    )


@pytest.mark.django_db
class TestProcessMonitorScanAck:
    def test_creates_snapshot_discovered_host_and_alert_for_new_hosts(
        self,
        online_gateway,
    ):
        gateway, agent = online_gateway
        command = _create_monitor_scan_command(
            agent,
            hosts=[
                {
                    "ip": "192.168.0.10",
                    "hostname": "printer.local",
                    "mac": "aa:bb:cc:dd:ee:01",
                },
                {
                    "ip": "192.168.0.11",
                    "hostname": "laptop.local",
                    "mac": "aa:bb:cc:dd:ee:02",
                },
            ],
            targets=["192.168.0.0/24", "192.168.1.0/24"],
        )

        process_monitor_scan_ack(command)

        snapshot = ScanSnapshot.objects.get(command=command)
        assert snapshot.gateway_id == gateway.id
        assert snapshot.chunk_cidrs == ["192.168.0.0/24", "192.168.1.0/24"]
        assert snapshot.host_count == 2
        assert snapshot.summary == {"host_count": 2}

        hosts = DiscoveredHost.objects.filter(gateway=gateway).order_by("ip")
        assert hosts.count() == 2
        assert list(hosts.values_list("ip", flat=True)) == ["192.168.0.10", "192.168.0.11"]
        assert all(host.is_new for host in hosts)

        alerts = MonitorAlert.objects.filter(gateway=gateway).order_by("host_ip")
        assert alerts.count() == 2
        assert alerts[0].alert_type == AlertType.NEW_HOST
        assert alerts[0].host_ip == "192.168.0.10"
        assert "192.168.0.10" in alerts[0].message
        assert alerts[1].host_ip == "192.168.0.11"

    def test_existing_host_updates_without_new_alert(self, online_gateway):
        gateway, agent = online_gateway
        first_scan = _create_monitor_scan_command(
            agent,
            hosts=[{"ip": "192.168.0.20", "hostname": "old-name", "mac": ""}],
        )
        process_monitor_scan_ack(first_scan)

        assert MonitorAlert.objects.filter(gateway=gateway).count() == 1

        second_scan = _create_monitor_scan_command(
            agent,
            hosts=[
                {
                    "ip": "192.168.0.20",
                    "hostname": "updated-name",
                    "mac": "aa:bb:cc:dd:ee:20",
                },
            ],
        )
        process_monitor_scan_ack(second_scan)

        host = DiscoveredHost.objects.get(gateway=gateway, ip="192.168.0.20")
        assert host.hostname == "updated-name"
        assert host.mac == "aa:bb:cc:dd:ee:20"
        assert host.is_new is False
        assert MonitorAlert.objects.filter(gateway=gateway).count() == 1
        assert ScanSnapshot.objects.filter(gateway=gateway).count() == 2

    def test_ignores_non_monitor_or_non_acked_commands(self, online_gateway):
        gateway, agent = online_gateway
        hosts = [{"ip": "192.168.0.30", "hostname": "", "mac": ""}]

        discover_cmd = _create_monitor_scan_command(
            agent,
            hosts=hosts,
            mode="discover",
        )
        pending_cmd = _create_monitor_scan_command(
            agent,
            hosts=hosts,
            state=CommandState.PENDING,
        )

        process_monitor_scan_ack(discover_cmd)
        process_monitor_scan_ack(pending_cmd)

        assert ScanSnapshot.objects.filter(gateway=gateway).count() == 0
        assert DiscoveredHost.objects.filter(gateway=gateway).count() == 0
        assert MonitorAlert.objects.filter(gateway=gateway).count() == 0


@pytest.mark.django_db
class TestRunMonitorScheduler:
    def test_enqueues_monitor_scan_when_policy_due(self, online_gateway):
        gateway, agent = online_gateway
        GatewayMonitorPolicy.objects.create(
            gateway=gateway,
            enabled=True,
            monitored_cidrs=["192.168.0.0/16"],
            discover_interval_minutes=60,
            chunk_count=4,
            last_scheduled_at=None,
        )

        scheduled = run_monitor_scheduler()

        assert scheduled == 1
        command = AgentCommand.objects.get(
            agent=agent,
            command="scan_network",
            state=CommandState.PENDING,
        )
        assert command.payload["mode"] == "monitor"
        assert command.payload["targets"] == [
            "192.168.0.0/24",
            "192.168.1.0/24",
            "192.168.2.0/24",
            "192.168.3.0/24",
        ]

        policy = GatewayMonitorPolicy.objects.get(gateway=gateway)
        assert policy.last_scheduled_at is not None
        assert policy.chunk_cursor == 4

    def test_skips_when_interval_not_elapsed(self, online_gateway):
        gateway, agent = online_gateway
        now = timezone.now()
        GatewayMonitorPolicy.objects.create(
            gateway=gateway,
            enabled=True,
            monitored_cidrs=["192.168.0.0/16"],
            discover_interval_minutes=60,
            last_scheduled_at=now - timedelta(minutes=30),
        )

        scheduled = run_monitor_scheduler()

        assert scheduled == 0
        assert not AgentCommand.objects.filter(agent=agent, command="scan_network").exists()

    def test_skips_offline_gateway(self, enrollment_credentials):
        gateway, agent, _ = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="offline-monitor-gw",
        )
        AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())
        GatewayMonitorPolicy.objects.create(
            gateway=gateway,
            enabled=True,
            monitored_cidrs=["192.168.0.0/16"],
        )

        assert run_monitor_scheduler() == 0
        assert not AgentCommand.objects.filter(agent=agent, command="scan_network").exists()


def _auth_header(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.mark.django_db
class TestAgentAckMonitorIntegration:
    def test_ack_view_persists_monitor_inventory(self, enrollment_credentials):
        gateway, agent, token = register_gateway_from_token(
            enrollment_credentials.raw_token,
            hostname="ack-monitor-gw",
        )
        gateway.status = GatewayStatus.ONLINE
        gateway.save(update_fields=["status"])
        AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())

        command = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "monitor", "targets": ["192.168.0.0/24"]},
            state=CommandState.DISPATCHED,
            dispatched_at=timezone.now(),
        )
        logs = _monitor_scan_logs(
            [{"ip": "192.168.0.42", "hostname": "device", "mac": ""}],
        )
        client = APIClient()
        response = client.post(
            reverse("agent-command-ack", kwargs={"agent_id": agent.id, "cmd_id": command.id}),
            data={"state": "acked", "result": {"exit_code": 0, "logs": logs}},
            content_type="application/json",
            **_auth_header(token),
        )
        assert response.status_code == 200

        assert ScanSnapshot.objects.filter(command=command).count() == 1
        assert DiscoveredHost.objects.filter(gateway=gateway, ip="192.168.0.42").count() == 1
        assert MonitorAlert.objects.filter(gateway=gateway, host_ip="192.168.0.42").count() == 1
