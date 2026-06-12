from __future__ import annotations

import json
from typing import Any

from agents.models import AgentCommand, CommandState
from lifecycle.deployment import login_server_url, tenant_production_mode
from tenants.detail import get_bootstrap_info
from tenants.models import Tenant

from gateways.models import Gateway


def resolve_login_server(tenant: Tenant) -> str:
    production = tenant_production_mode(tenant.desired_config)
    return login_server_url(tenant.headscale_host, production=production)


def resolve_gateway_auth_key(tenant: Tenant) -> str:
    info = get_bootstrap_info(tenant)
    auth_key = (info or {}).get("auth_key_gateway")
    if not auth_key:
        msg = "auth_key_gateway is not available for this tenant"
        raise ValueError(msg)
    return str(auth_key)


def tenant_credentials_ready(tenant: Tenant) -> bool:
    try:
        resolve_gateway_auth_key(tenant)
    except ValueError:
        return False
    return True


def get_latest_acked_scan_command(gateway: Gateway) -> AgentCommand | None:
    """Return the newest ACKED scan among latest discover and target commands."""
    from gateways.services import get_latest_scan_command

    candidates: list[AgentCommand] = []
    for scan_mode in ("discover", "target"):
        command = get_latest_scan_command(gateway, scan_mode)
        if command is not None and command.state == CommandState.ACKED:
            candidates.append(command)

    if not candidates:
        return None

    def _sort_key(cmd: AgentCommand) -> tuple[Any, Any]:
        return (cmd.acked_at or cmd.created_at, cmd.created_at)

    return max(candidates, key=_sort_key)


def parse_scan_subnets(command: AgentCommand | None) -> list[str]:
    parsed = parse_scan_result(command)
    if parsed is None:
        return []
    return [subnet["cidr"] for subnet in parsed.get("subnets", []) if subnet.get("cidr")]


def parse_scan_result(command: AgentCommand | None) -> dict[str, Any] | None:
    if command is None:
        return None

    result = dict(command.result or {})
    body = _scan_body_from_result(result)
    if body is None:
        return None

    subnets = body.get("subnets")
    if not isinstance(subnets, list):
        return None

    payload = dict(command.payload or {})
    scan_mode = body.get("scan_mode")
    if scan_mode not in ("discover", "target"):
        scan_mode = payload.get("mode", "discover")

    summary = body.get("summary")
    if not isinstance(summary, dict):
        summary = _default_scan_summary(subnets)

    return {
        "command_id": str(command.id),
        "scan_mode": scan_mode,
        "acked_at": command.acked_at.isoformat() if command.acked_at else None,
        "subnets": subnets,
        "summary": summary,
    }


def _scan_body_from_result(result: dict[str, Any]) -> dict[str, Any] | None:
    logs = result.get("logs")
    if isinstance(logs, str) and logs.strip():
        try:
            body = json.loads(logs)
        except json.JSONDecodeError:
            return None
        if isinstance(body, dict):
            return body

    raw_subnets = result.get("subnets")
    if isinstance(raw_subnets, list):
        return {"subnets": raw_subnets}

    return None


def _default_scan_summary(subnets: list[Any]) -> dict[str, int]:
    total_hosts = 0
    local_networks = 0
    target_networks = 0
    for item in subnets:
        if not isinstance(item, dict):
            continue
        live_hosts = item.get("live_hosts")
        hosts = item.get("hosts")
        if isinstance(live_hosts, int):
            total_hosts += live_hosts
        elif isinstance(hosts, list):
            total_hosts += len(hosts)
        if item.get("is_local"):
            local_networks += 1
        else:
            target_networks += 1

    return {
        "subnet_count": len(subnets),
        "total_hosts": total_hosts,
        "local_networks": local_networks,
        "target_networks": target_networks,
    }


def format_advertise_routes(routes: list[str]) -> str:
    return ",".join(routes)


def build_tailscale_up_payload(
    gateway: Gateway,
    *,
    tenant_id: str,
    advertise_routes: list[str],
    force_reauth: bool = True,
    accept_dns: bool = True,
    reset: bool = True,
) -> dict[str, Any]:
    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist as exc:
        msg = "Tenant not found"
        raise ValueError(msg) from exc

    login_server = resolve_login_server(tenant)
    auth_key = resolve_gateway_auth_key(tenant)

    return {
        "login_server": login_server,
        "auth_key": auth_key,
        "advertise_routes": format_advertise_routes(advertise_routes),
        "custom_tags": list(gateway.custom_tags),
        "force_reauth": force_reauth,
        "accept_dns": accept_dns,
        "reset": reset,
    }


def mask_auth_key_hint(key: str) -> str:
    text = str(key).strip()
    if len(text) <= 4:
        return f"…{text}"
    return f"…{text[-4:]}"


def _tenant_preview(tenant: Tenant) -> dict[str, Any]:
    login_server = resolve_login_server(tenant)
    try:
        auth_key = resolve_gateway_auth_key(tenant)
        auth_key_hint = mask_auth_key_hint(auth_key)
        auth_key_available = True
    except ValueError:
        auth_key_hint = None
        auth_key_available = False

    return {
        "tenant_id": str(tenant.id),
        "slug": tenant.slug,
        "login_server": login_server,
        "auth_key_available": auth_key_available,
        "auth_key_hint": auth_key_hint,
    }


def _tenant_option(tenant: Tenant) -> dict[str, Any]:
    return {
        "id": str(tenant.id),
        "slug": tenant.slug,
        "headscale_host": tenant.headscale_host,
        "bootstrap_status": tenant.bootstrap_status,
        "credentials_ready": tenant_credentials_ready(tenant),
    }


def build_tailscale_connect_context(
    gateway: Gateway,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    if tenant_id is not None:
        tenant = Tenant.objects.get(id=tenant_id)
    else:
        tenant = gateway.tenant

    scan_command = get_latest_acked_scan_command(gateway)
    last_scan = parse_scan_result(scan_command)

    return {
        "gateway_tenant_id": str(gateway.tenant_id),
        "tenants": [_tenant_option(item) for item in Tenant.objects.order_by("slug")],
        "default_tenant_id": str(gateway.tenant_id),
        "tenant_preview": _tenant_preview(tenant),
        "last_scan": last_scan,
        "option_defaults": {
            "force_reauth": True,
            "accept_dns": True,
            "reset": True,
        },
    }
