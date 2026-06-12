from __future__ import annotations

from typing import Any

from django.utils import timezone

from agents.models import AgentCommand, CommandState
from tenants.bootstrap_secrets import extract_bootstrap_secrets, resolve_bootstrap_secrets
from tenants.models import Tenant, TenantHealth

HEALTH_CHECK_HISTORY_LIMIT = 5


HEALTH_CHECK_HISTORY_LIMIT = 5


def persist_bootstrap_secrets(tenant: Tenant, bootstrap: dict[str, Any] | None) -> None:
    resolve_bootstrap_secrets(tenant, bootstrap, persist=True)


def get_bootstrap_info(tenant: Tenant) -> dict[str, Any] | None:
    command = (
        AgentCommand.objects.filter(
            command="bootstrap_tenant",
            payload__tenant_id=str(tenant.id),
            state=CommandState.ACKED,
        )
        .order_by("-acked_at")
        .first()
    )

    bootstrap = dict((command.result or {}).get("bootstrap") or {}) if command else {}
    secrets = resolve_bootstrap_secrets(tenant, bootstrap, persist=True)

    if not secrets and command is None and not tenant.bootstrap_output_ref:
        return None

    def _value(key: str) -> str | None:
        value = secrets.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    return {
        "command_id": str(command.id) if command else None,
        "acked_at": command.acked_at.isoformat() if command and command.acked_at else None,
        "admin_user_id": _value("admin_user_id"),
        "api_key": _value("api_key"),
        "auth_key_gateway": _value("auth_key_gateway"),
        "auth_key_workspace": _value("auth_key_workspace"),
        "output_ref": bootstrap.get("output_ref") or tenant.bootstrap_output_ref or None,
    }


def recent_health_checks(tenant: Tenant) -> list[TenantHealth]:
    return list(
        TenantHealth.objects.filter(tenant=tenant)
        .order_by("-probed_at")[:HEALTH_CHECK_HISTORY_LIMIT],
    )


def record_health_from_verify(command: AgentCommand, tenant: Tenant) -> TenantHealth | None:
    if command.command != "verify_tenant":
        return None
    if command.state not in {CommandState.ACKED, CommandState.FAILED}:
        return None

    existing = TenantHealth.objects.filter(source_command=command).first()
    if existing is not None:
        return existing

    result = dict(command.result or {})
    healthy = command.state == CommandState.ACKED and result.get("exit_code") == 0
    duration_ms = result.get("duration_ms", 0)
    try:
        latency_ms = max(0, min(int(duration_ms), 999_999))
    except (TypeError, ValueError):
        latency_ms = 0

    error_message = ""
    if not healthy:
        logs = result.get("logs")
        if isinstance(logs, str) and logs.strip():
            error_message = logs.strip()

    health = TenantHealth.objects.create(
        tenant=tenant,
        source_command=command,
        probed_at=command.acked_at or timezone.now(),
        latency_ms=latency_ms,
        healthy=healthy,
        error_message=error_message,
    )
    _trim_health_history(tenant)
    return health


def _trim_health_history(tenant: Tenant) -> None:
    keep_ids = list(
        TenantHealth.objects.filter(tenant=tenant)
        .order_by("-probed_at")
        .values_list("id", flat=True)[:HEALTH_CHECK_HISTORY_LIMIT],
    )
    if not keep_ids:
        return
    TenantHealth.objects.filter(tenant=tenant).exclude(id__in=keep_ids).delete()
