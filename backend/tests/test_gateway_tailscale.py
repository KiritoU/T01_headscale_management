from __future__ import annotations

import json
from typing import Any

import pytest
from django.urls import reverse
from django.utils import timezone

from agent_daemon.gateway_daemon import GatewayDaemon
from agents.models import AgentCommand, AgentModule, CommandState
from gateways.models import Gateway
from gateways.services import register_gateway_from_token
from gateways.tailscale import (
    build_tailscale_connect_context,
    build_tailscale_up_payload,
    format_advertise_routes,
    get_latest_acked_scan_command,
    mask_auth_key_hint,
    parse_scan_subnets,
    resolve_gateway_auth_key,
    resolve_login_server,
)
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker():
    return Worker.objects.create(name="ts-worker", hostname="ts.vps.example.com")


@pytest.fixture
def tenant(worker):
    return Tenant.objects.create(
        slug="team-ts",
        headscale_host="headscale-team-ts.example.com",
        headplane_host="headplane-team-ts.example.com",
        db_name="hs_team_ts",
        worker=worker,
        desired_config={"production": True},
        bootstrap_secrets={
            "auth_key_gateway": "tskey-auth-gw-secret1234",
            "api_key": "hskey-api-test",
        },
    )


@pytest.fixture
def enrolled_gateway(tenant, enrollment_credentials):
    gateway, agent, _ = register_gateway_from_token(
        enrollment_credentials.raw_token,
        hostname="ts-gateway",
    )
    AgentModule.objects.create(agent=agent, name="tailscale", installed_at=timezone.now())
    return gateway, agent


@pytest.fixture
def enrollment_credentials(tenant):
    from gateways.services import create_enrollment_token

    return create_enrollment_token(tenant, max_uses=2)


def _scan_logs(cidr: str) -> str:
    return json.dumps(
        {
            "scan_mode": "discover",
            "subnets": [{"cidr": cidr, "interface": "eth0", "live_hosts": 1}],
        },
    )


@pytest.mark.django_db
class TestTailscaleHelpers:
    def test_resolve_login_server_uses_production_mode(self, tenant):
        assert resolve_login_server(tenant) == (
            "https://headscale-team-ts.example.com"
        )

    def test_resolve_login_server_dev_mode(self, tenant):
        tenant.desired_config = {}
        tenant.save(update_fields=["desired_config"])
        assert resolve_login_server(tenant) == (
            "http://headscale-team-ts.example.com"
        )

    def test_resolve_gateway_auth_key_requires_secret(self, tenant):
        tenant.bootstrap_secrets = {}
        tenant.save(update_fields=["bootstrap_secrets"])

        with pytest.raises(ValueError, match="auth_key_gateway"):
            resolve_gateway_auth_key(tenant)

    def test_resolve_gateway_auth_key_from_bootstrap_secrets(self, tenant):
        assert resolve_gateway_auth_key(tenant) == "tskey-auth-gw-secret1234"

    def test_format_advertise_routes(self):
        assert format_advertise_routes(["10.0.0.0/24", "192.168.1.0/24"]) == (
            "10.0.0.0/24,192.168.1.0/24"
        )

    def test_mask_auth_key_hint(self):
        assert mask_auth_key_hint("tskey-auth-gw-secret1234") == "…1234"

    def test_get_latest_acked_scan_picks_newest(self, enrolled_gateway):
        gateway, agent = enrolled_gateway
        older = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            acked_at=timezone.now() - timezone.timedelta(hours=2),
            result={"logs": _scan_logs("10.0.0.0/24")},
        )
        newer = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "target", "targets": ["192.168.50.0/24"]},
            state=CommandState.ACKED,
            acked_at=timezone.now() - timezone.timedelta(hours=1),
            result={"logs": _scan_logs("192.168.50.0/24")},
        )
        AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.PENDING,
            result={"logs": _scan_logs("172.16.0.0/24")},
        )

        latest = get_latest_acked_scan_command(gateway)

        assert latest is not None
        assert latest.id == newer.id
        assert latest.id != older.id

    def test_parse_scan_subnets_from_logs(self, enrolled_gateway):
        _, agent = enrolled_gateway
        command = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            result={"logs": _scan_logs("192.168.100.0/24")},
        )

        assert parse_scan_subnets(command) == ["192.168.100.0/24"]

    def test_parse_scan_subnets_from_result_subnets(self, enrolled_gateway):
        _, agent = enrolled_gateway
        command = AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            result={"subnets": [{"cidr": "10.10.0.0/24"}]},
        )

        assert parse_scan_subnets(command) == ["10.10.0.0/24"]

    def test_build_tailscale_up_payload(self, enrolled_gateway, tenant):
        gateway, _ = enrolled_gateway
        Gateway.objects.filter(pk=gateway.pk).update(
            custom_tags=["tag:gateway", "tag:site-test"],
        )
        gateway.refresh_from_db()

        payload = build_tailscale_up_payload(
            gateway,
            tenant_id=str(tenant.id),
            advertise_routes=["10.0.0.0/24", "192.168.1.0/24"],
        )

        assert payload["login_server"] == "https://headscale-team-ts.example.com"
        assert payload["auth_key"] == "tskey-auth-gw-secret1234"
        assert payload["advertise_routes"] == "10.0.0.0/24,192.168.1.0/24"
        assert payload["custom_tags"] == ["tag:gateway", "tag:site-test"]
        assert payload["force_reauth"] is True
        assert payload["accept_dns"] is True
        assert payload["reset"] is True

    def test_build_tailscale_connect_context_masks_auth_key(self, enrolled_gateway, tenant):
        gateway, agent = enrolled_gateway
        AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            acked_at=timezone.now(),
            result={"logs": _scan_logs("192.168.200.0/24")},
        )

        context = build_tailscale_connect_context(gateway)

        assert context["gateway_tenant_id"] == str(tenant.id)
        assert context["default_tenant_id"] == str(tenant.id)
        assert context["tenant_preview"]["tenant_id"] == str(tenant.id)
        assert context["tenant_preview"]["login_server"] == (
            "https://headscale-team-ts.example.com"
        )
        assert context["last_scan"]["subnets"][0]["cidr"] == "192.168.200.0/24"
        assert context["tenant_preview"]["auth_key_hint"] == "…1234"
        assert context["tenant_preview"]["auth_key_available"] is True
        assert context["option_defaults"]["force_reauth"] is True
        assert "tskey-auth-gw-secret1234" not in json.dumps(context)


@pytest.mark.django_db
class TestTailscaleConnectContextAPI:
    def test_context_api_returns_scan_subnets_without_full_auth_key(
        self,
        client,
        enrolled_gateway,
        tenant,
    ):
        gateway, agent = enrolled_gateway
        AgentCommand.objects.create(
            agent=agent,
            command="scan_network",
            payload={"mode": "discover"},
            state=CommandState.ACKED,
            acked_at=timezone.now(),
            result={"logs": _scan_logs("192.168.77.0/24")},
        )

        response = client.get(
            reverse("gateway-tailscale-up-context", kwargs={"gateway_id": gateway.id}),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["last_scan"]["subnets"][0]["cidr"] == "192.168.77.0/24"
        assert data["tenant_preview"]["auth_key_hint"] == "…1234"
        assert data["tenant_preview"]["auth_key_available"] is True
        assert data["tenants"]
        assert "secret1234" not in json.dumps(data)

    def test_context_api_denies_cross_tenant_without_grant(
        self,
        client,
        admin_user,
        editor_user,
        enrolled_gateway,
        tenant,
        worker,
    ):
        from accounts.models import AccessLevel, ResourceGrant, ScopeType

        gateway, _ = enrolled_gateway
        other_tenant = Tenant.objects.create(
            slug="team-other-ts",
            headscale_host="headscale-other-ts.example.com",
            headplane_host="headplane-other-ts.example.com",
            db_name="hs_other_ts",
            worker=worker,
            desired_config={"production": True},
            bootstrap_secrets={"auth_key_gateway": "tskey-other-secret5678"},
        )
        ResourceGrant.objects.create(
            user=editor_user,
            scope_type=ScopeType.GATEWAY,
            scope_id=gateway.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )
        client.force_login(editor_user)

        denied = client.get(
            reverse("gateway-tailscale-up-context", kwargs={"gateway_id": gateway.id}),
            {"tenant_id": str(other_tenant.id)},
        )

        assert denied.status_code == 403

        ResourceGrant.objects.create(
            user=editor_user,
            scope_type=ScopeType.TENANT,
            scope_id=other_tenant.id,
            access_level=AccessLevel.VIEW,
            granted_by=admin_user,
        )

        allowed = client.get(
            reverse("gateway-tailscale-up-context", kwargs={"gateway_id": gateway.id}),
            {"tenant_id": str(other_tenant.id)},
        )

        assert allowed.status_code == 200
        assert allowed.json()["data"]["tenant_preview"]["tenant_id"] == str(other_tenant.id)


@pytest.mark.django_db
class TestTailscaleUpCommandAPI:
    def test_post_tailscale_up_with_tenant_id_resolves_secrets(
        self,
        client,
        enrolled_gateway,
        tenant,
    ):
        gateway, agent = enrolled_gateway

        response = client.post(
            reverse("gateway-commands", kwargs={"gateway_id": gateway.id}),
            data={
                "command": "tailscale_up",
                "payload": {
                    "tenant_id": str(tenant.id),
                    "advertise_routes": ["10.0.0.0/24"],
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 201
        body = response.json()
        assert body["success"] is True
        assert body["data"]["payload"]["auth_key"] == "[redacted]"
        cmd = AgentCommand.objects.get(id=body["data"]["id"])
        assert cmd.agent_id == agent.id
        assert cmd.payload["login_server"] == "https://headscale-team-ts.example.com"
        assert cmd.payload["auth_key"] == "tskey-auth-gw-secret1234"
        assert cmd.payload["advertise_routes"] == "10.0.0.0/24"
        assert cmd.payload["custom_tags"] == ["tag:gateway"]

    def test_post_tailscale_up_rejects_missing_auth_key(
        self,
        client,
        enrolled_gateway,
        tenant,
    ):
        gateway, _ = enrolled_gateway
        tenant.bootstrap_secrets = {}
        tenant.save(update_fields=["bootstrap_secrets"])

        response = client.post(
            reverse("gateway-commands", kwargs={"gateway_id": gateway.id}),
            data={
                "command": "tailscale_up",
                "payload": {
                    "tenant_id": str(tenant.id),
                    "advertise_routes": ["10.0.0.0/24"],
                },
            },
            content_type="application/json",
        )

        assert response.status_code == 400
        body = response.json()
        assert body["success"] is False
        assert "auth_key_gateway" in body["error"]


class TestTailscaleDaemonAcceptRoutes:
    def test_daemon_omits_accept_routes_by_default(self) -> None:
        captured: list[list[str]] = []

        def tailscale_runner(args: list[str]) -> Any:
            captured.append(list(args))
            return type(
                "Proc",
                (),
                {"stdout": "Success.", "stderr": "", "returncode": 0},
            )()

        daemon = GatewayDaemon(
            client=type("Client", (), {"heartbeat": lambda *_: None, "poll": lambda *_: {"commands": []}, "ack": lambda *_: None})(),
            tailscale_runner=tailscale_runner,
        )
        daemon._state = type(daemon.state)(installed_modules=frozenset({"core", "tailscale"}))

        result, state = daemon._handle_tailscale_up(
            {
                "login_server": "https://hs.example.com",
                "auth_key": "tskey-test",
                "advertise_routes": "10.0.0.0/24",
                "accept_dns": True,
                "force_reauth": True,
                "reset": True,
            },
        )

        assert state == "acked"
        command_args = captured[0]
        assert "--accept-routes" not in command_args
        assert "--accept-dns" in command_args
        assert "--force-reauth" in command_args
        assert "--reset" in command_args

    def test_daemon_adds_accept_routes_when_explicitly_true(self) -> None:
        captured: list[list[str]] = []

        def tailscale_runner(args: list[str]) -> Any:
            captured.append(list(args))
            return type(
                "Proc",
                (),
                {"stdout": "Success.", "stderr": "", "returncode": 0},
            )()

        daemon = GatewayDaemon(
            client=type("Client", (), {})(),
            tailscale_runner=tailscale_runner,
        )
        daemon._state = type(daemon.state)(installed_modules=frozenset({"core", "tailscale"}))

        daemon._handle_tailscale_up(
            {
                "login_server": "https://hs.example.com",
                "accept_routes": True,
            },
        )

        assert "--accept-routes" in captured[0]

