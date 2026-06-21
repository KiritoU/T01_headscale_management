from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccessLevel, ResourceGrant, ScopeType
from agents.models import AgentCommand, AgentModule, CommandState
from gateways.models import DiscoveredHost, GatewayMonitorPolicy, GatewayStatus
from gateways.services import create_enrollment_token, register_gateway_from_token
from tenants.models import Tenant
from workers.models import Worker


def _grant(*, user, scope_type, scope_id, access_level, granted_by):
    return ResourceGrant.objects.create(
        user=user,
        scope_type=scope_type,
        scope_id=scope_id,
        access_level=access_level,
        granted_by=granted_by,
    )


@pytest.fixture
def worker():
    return Worker.objects.create(name="monitor-api-worker", hostname="monitor-api.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-monitor-api",
        headscale_host="hs-monitor-api.example.com",
        headplane_host="hp-monitor-api.example.com",
        db_name="hs_team_monitor_api",
        worker=worker,
    )


@pytest.fixture
def enrollment_credentials(tenant):
    return create_enrollment_token(tenant, max_uses=3)


@pytest.fixture
def gateway(enrollment_credentials):
    gateway, agent, _ = register_gateway_from_token(
        enrollment_credentials.raw_token,
        hostname="monitor-api-gw",
    )
    gateway.status = GatewayStatus.ONLINE
    gateway.save(update_fields=["status"])
    return gateway, agent


def _monitoring_url(gateway_id):
    return reverse("gateway-monitoring", kwargs={"gateway_id": gateway_id})


def _ensure_modules_url(gateway_id):
    return reverse("gateway-monitoring-ensure-modules", kwargs={"gateway_id": gateway_id})


def _scan_url(gateway_id):
    return reverse("gateway-monitoring-scan", kwargs={"gateway_id": gateway_id})


def _vuln_rescan_url(gateway_id):
    return reverse("gateway-monitoring-vuln-rescan", kwargs={"gateway_id": gateway_id})


def _hosts_url(gateway_id):
    return reverse("gateway-monitoring-hosts", kwargs={"gateway_id": gateway_id})


def _alerts_url(gateway_id):
    return reverse("gateway-monitoring-alerts", kwargs={"gateway_id": gateway_id})


def _findings_url(gateway_id):
    return reverse("gateway-monitoring-findings", kwargs={"gateway_id": gateway_id})


@pytest.mark.django_db
class TestGatewayMonitoringAPI:
    def test_get_monitoring_creates_default_policy(self, auth_client, gateway):
        gw, _agent = gateway

        response = auth_client.get(_monitoring_url(gw.id))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["enabled"] is False
        assert data["monitored_cidrs"] == ["192.168.0.0/16"]
        assert data["min_interval_minutes"] == 10
        assert data["nuclei_enabled"] is True
        assert data["vuln_rescan_days"] == 1
        assert GatewayMonitorPolicy.objects.filter(gateway=gw).exists()

    def test_patch_rejects_discover_interval_below_minimum(self, auth_client, gateway):
        gw, _agent = gateway
        auth_client.patch(
            _monitoring_url(gw.id),
            data={"scan_strategy": "full_sweep"},
            format="json",
        )

        response = auth_client.patch(
            _monitoring_url(gw.id),
            data={"discover_interval_minutes": 1},
            format="json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "at least" in body["error"]

    def test_patch_accepts_valid_discover_interval(self, auth_client, gateway):
        gw, _agent = gateway

        response = auth_client.patch(
            _monitoring_url(gw.id),
            data={
                "enabled": True,
                "discover_interval_minutes": 60,
            },
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["enabled"] is True
        assert body["data"]["discover_interval_minutes"] == 60

        policy = GatewayMonitorPolicy.objects.get(gateway=gw)
        assert policy.enabled is True
        assert policy.discover_interval_minutes == 60


@pytest.mark.django_db
class TestGatewayMonitoringEnsureModulesAPI:
    def test_ensure_modules_enqueues_install_module(self, auth_client, gateway):
        gw, agent = gateway

        response = auth_client.post(_ensure_modules_url(gw.id))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["ready"] is False

        install_cmd = AgentCommand.objects.get(
            agent=agent,
            command="install_module",
            state=CommandState.PENDING,
        )
        assert install_cmd.payload == {"module": "masscan"}

        masscan_status = next(
            item
            for item in body["data"]["policy"]["module_statuses"]
            if item["module_id"] == "masscan"
        )
        assert masscan_status["status"] == "pending"

    def test_ensure_modules_ready_when_masscan_installed(self, auth_client, gateway):
        gw, agent = gateway
        AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())

        response = auth_client.post(_ensure_modules_url(gw.id))

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["ready"] is True
        assert not AgentCommand.objects.filter(agent=agent, command="install_module").exists()


@pytest.mark.django_db
class TestGatewayMonitoringRBAC:
    def test_viewer_cannot_patch_monitoring(
        self,
        client,
        admin_user,
        viewer_user,
        tenant,
        gateway,
    ):
        gw, _agent = gateway
        _grant(
            user=viewer_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        client.force_login(viewer_user)

        response = client.patch(
            _monitoring_url(gw.id),
            data={"enabled": True},
            content_type="application/json",
        )

        assert response.status_code == 403

    def test_editor_with_view_grant_can_read_but_not_patch(
        self,
        client,
        admin_user,
        editor_user,
        gateway,
    ):
        gw, _agent = gateway
        _grant(
            user=editor_user,
            scope_type=ScopeType.GATEWAY,
            scope_id=gw.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        client.force_login(editor_user)

        get_response = client.get(_monitoring_url(gw.id))
        patch_response = client.patch(
            _monitoring_url(gw.id),
            data={"enabled": True},
            content_type="application/json",
        )

        assert get_response.status_code == 200
        assert patch_response.status_code == 403

    def test_editor_with_edit_grant_can_patch_monitoring(
        self,
        client,
        admin_user,
        editor_user,
        gateway,
    ):
        gw, _agent = gateway
        _grant(
            user=editor_user,
            scope_type=ScopeType.GATEWAY,
            scope_id=gw.id,
            access_level=AccessLevel.EDIT,
            granted_by=admin_user,
        )
        client.force_login(editor_user)

        response = client.patch(
            _monitoring_url(gw.id),
            data={"enabled": True, "discover_interval_minutes": 60},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is True


@pytest.mark.django_db
class TestGatewayMonitoringScanAPI:
    def test_trigger_scan_enqueues_monitor_command(self, auth_client, gateway):
        gw, agent = gateway
        AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())
        GatewayMonitorPolicy.objects.create(
            gateway=gw,
            enabled=True,
            monitored_cidrs=["192.168.0.0/16"],
            discover_interval_minutes=60,
            chunk_count=2,
            last_scheduled_at=timezone.now(),
        )

        response = auth_client.post(_scan_url(gw.id))

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["targets"] == ["192.168.0.0/24", "192.168.1.0/24"]
        command = AgentCommand.objects.get(
            agent=agent,
            command="scan_network",
            state=CommandState.PENDING,
        )
        assert command.payload["mode"] == "monitor"
        assert str(command.id) == body["data"]["command_id"]

    def test_trigger_scan_rejects_when_scan_already_pending(self, auth_client, gateway):
        gw, agent = gateway
        AgentModule.objects.create(agent=agent, name="masscan", installed_at=timezone.now())
        GatewayMonitorPolicy.objects.create(
            gateway=gw,
            enabled=True,
            monitored_cidrs=["192.168.0.0/16"],
        )
        AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "monitor", "targets": ["192.168.0.0/24"]},
            state=CommandState.PENDING,
        )

        response = auth_client.post(_scan_url(gw.id))

        assert response.status_code == 409
        assert "already" in response.json()["error"].lower()

    def test_viewer_cannot_trigger_scan(
        self,
        client,
        admin_user,
        viewer_user,
        tenant,
        gateway,
    ):
        gw, _agent = gateway
        _grant(
            user=viewer_user,
            scope_type=ScopeType.TENANT,
            scope_id=tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        client.force_login(viewer_user)

        response = client.post(_scan_url(gw.id))

        assert response.status_code == 403


@pytest.mark.django_db
class TestGatewayMonitoringVulnRescanAPI:
    def _install_vuln_modules(self, agent) -> None:
        for module_name in ("nmap", "vuln-nse-pack", "iot-probes", "nuclei"):
            AgentModule.objects.create(
                agent=agent,
                name=module_name,
                installed_at=timezone.now(),
            )

    def test_trigger_vuln_rescan_queues_hosts(self, auth_client, gateway):
        gw, agent = gateway
        self._install_vuln_modules(agent)
        GatewayMonitorPolicy.objects.create(
            gateway=gw,
            enabled=True,
            vuln_scan_enabled=True,
            nuclei_enabled=True,
        )
        now = timezone.now()
        host = DiscoveredHost.objects.create(
            gateway=gw,
            ip="192.168.103.101",
            open_ports=[22, 3000],
            vuln_scan_pending=False,
            first_seen_at=now,
            last_seen_at=now,
        )

        response = auth_client.post(_vuln_rescan_url(gw.id))

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["queued_count"] == 1
        assert body["data"]["hosts"] == ["192.168.103.101"]
        host.refresh_from_db()
        assert host.vuln_scan_pending is True

    def test_trigger_vuln_rescan_for_specific_ip(self, auth_client, gateway):
        gw, agent = gateway
        self._install_vuln_modules(agent)
        GatewayMonitorPolicy.objects.create(
            gateway=gw,
            enabled=True,
            vuln_scan_enabled=True,
            nuclei_enabled=True,
        )
        now = timezone.now()
        target = DiscoveredHost.objects.create(
            gateway=gw,
            ip="192.168.103.101",
            open_ports=[3000],
            first_seen_at=now,
            last_seen_at=now,
        )
        DiscoveredHost.objects.create(
            gateway=gw,
            ip="192.168.103.100",
            open_ports=[22],
            first_seen_at=now,
            last_seen_at=now,
        )

        response = auth_client.post(
            _vuln_rescan_url(gw.id),
            data={"ip": "192.168.103.101"},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["data"]["hosts"] == ["192.168.103.101"]
        target.refresh_from_db()
        assert target.vuln_scan_pending is True
        other = DiscoveredHost.objects.get(gateway=gw, ip="192.168.103.100")
        assert other.vuln_scan_pending is False


@pytest.mark.django_db
class TestGatewayMonitoringPaginationAPI:
    def test_hosts_pagination_and_ip_filter(self, auth_client, gateway):
        gw, _agent = gateway
        now = timezone.now()
        for index in range(3):
            DiscoveredHost.objects.create(
                gateway=gw,
                ip=f"192.168.10.{index + 1}",
                first_seen_at=now,
                last_seen_at=now,
                is_new=index == 0,
            )

        response = auth_client.get(_hosts_url(gw.id), {"page": 1, "limit": 2})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["meta"]["total"] == 3
        assert body["meta"]["pages"] == 2

        filtered = auth_client.get(
            _hosts_url(gw.id),
            {"ip": "192.168.10.1", "is_new": "true"},
        )
        assert filtered.status_code == 200
        filtered_body = filtered.json()
        assert filtered_body["meta"]["total"] == 1
        assert filtered_body["data"][0]["ip"] == "192.168.10.1"

    def test_findings_pagination_and_severity_filter(self, auth_client, gateway):
        from gateways.models import Severity, VulnFinding

        gw, _agent = gateway
        now = timezone.now()
        host = DiscoveredHost.objects.create(
            gateway=gw,
            ip="192.168.20.10",
            first_seen_at=now,
            last_seen_at=now,
        )
        VulnFinding.objects.create(
            discovered_host=host,
            source="nuclei",
            severity=Severity.HIGH,
            title="High finding",
            finding_id="test:high",
            found_at=now,
        )
        VulnFinding.objects.create(
            discovered_host=host,
            source="web-audit",
            severity=Severity.INFO,
            title="Info finding",
            finding_id="test:info",
            found_at=now,
        )

        response = auth_client.get(
            _findings_url(gw.id),
            {"severity": "high", "source": "nuclei"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["severity"] == "high"
        assert body["data"][0]["source"] == "nuclei"

    def test_alerts_pagination_and_host_filter(self, auth_client, gateway):
        from gateways.models import AlertType, MonitorAlert

        gw, _agent = gateway
        MonitorAlert.objects.create(
            gateway=gw,
            alert_type=AlertType.NEW_HOST,
            host_ip="192.168.30.5",
            message="new host seen",
        )
        MonitorAlert.objects.create(
            gateway=gw,
            alert_type=AlertType.NEW_HOST,
            host_ip="192.168.30.99",
            message="another host",
        )

        response = auth_client.get(
            _alerts_url(gw.id),
            {"host_ip": "192.168.30.5", "limit": 10},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["host_ip"] == "192.168.30.5"
