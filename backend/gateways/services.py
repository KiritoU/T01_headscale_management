from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentModule, AgentType
from agents.services import create_agent_token
from gateways.models import EnrollmentToken, Gateway, GatewayStatus

ENROLL_TOKEN_PREFIX = "enrl_"
ENROLL_TOKEN_RANDOM_BYTES = 32

GATEWAY_COMMANDS = frozenset(
    {"scan_network", "tailscale_up", "tailscale_status", "install_module", "vuln_scan"},
)
TAILSCALE_COMMANDS = frozenset({"tailscale_up", "tailscale_status"})


@dataclass(frozen=True)
class EnrollmentTokenCredentials:
    token_id: str
    tenant_id: str
    raw_token: str
    prefix: str
    max_uses: int
    expires_at: str | None


def _hash_enroll_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_enrollment_token(
    tenant,
    *,
    max_uses: int = 1,
    expires_at: datetime | None = None,
    expires_in_minutes: int = 60,
) -> EnrollmentTokenCredentials:
    if expires_at is None:
        expires_at = timezone.now() + timedelta(minutes=expires_in_minutes)
    random_part = secrets.token_urlsafe(ENROLL_TOKEN_RANDOM_BYTES)
    raw_token = f"{ENROLL_TOKEN_PREFIX}{random_part}"
    prefix = raw_token[:8]
    token_hash = _hash_enroll_token(raw_token)

    token = EnrollmentToken.objects.create(
        tenant=tenant,
        token_hash=token_hash,
        prefix=prefix,
        max_uses=max_uses,
        expires_at=expires_at,
    )

    return EnrollmentTokenCredentials(
        token_id=str(token.id),
        tenant_id=str(tenant.id),
        raw_token=raw_token,
        prefix=prefix,
        max_uses=max_uses,
        expires_at=expires_at.isoformat() if expires_at else None,
    )


def revoke_enrollment_token(token: EnrollmentToken) -> EnrollmentToken:
    EnrollmentToken.objects.filter(pk=token.pk).update(revoked=True)
    token.refresh_from_db()
    return token


def _lookup_enrollment_token(raw_token: str) -> EnrollmentToken | None:
    if not raw_token.startswith(ENROLL_TOKEN_PREFIX) or len(raw_token) < 8:
        return None

    prefix = raw_token[:8]
    token_hash = _hash_enroll_token(raw_token)

    try:
        return EnrollmentToken.objects.select_related("tenant").get(
            prefix=prefix,
            token_hash=token_hash,
        )
    except EnrollmentToken.DoesNotExist:
        return None


def _validate_enrollment_token(token: EnrollmentToken) -> None:
    if token.revoked:
        msg = "Enrollment token is revoked"
        raise ValueError(msg)
    if token.expires_at and token.expires_at <= timezone.now():
        msg = "Enrollment token is expired"
        raise ValueError(msg)
    if token.uses >= token.max_uses:
        msg = "Enrollment token is exhausted"
        raise ValueError(msg)


@transaction.atomic
def register_gateway_from_token(
    raw_token: str,
    *,
    hostname: str = "",
) -> tuple[Gateway, Agent, str]:
    token = _lookup_enrollment_token(raw_token)
    if token is None:
        msg = "Invalid enrollment token"
        raise ValueError(msg)

    _validate_enrollment_token(token)

    creds = create_agent_token()
    agent = Agent.objects.create(
        agent_type=AgentType.GATEWAY,
        token_prefix=creds.token_prefix,
        token_hash=creds.token_hash,
    )

    gateway = Gateway.objects.create(
        tenant=token.tenant,
        hostname=hostname,
        status=GatewayStatus.ENROLLED,
        agent=agent,
        enrollment_token_ref=token.prefix,
        custom_tags=["tag:gateway"],
    )

    EnrollmentToken.objects.filter(pk=token.pk).update(uses=token.uses + 1)

    return gateway, agent, creds.raw_token


def _gateway_has_module(gateway: Gateway, module_name: str) -> bool:
    if gateway.agent_id is None:
        return False
    return AgentModule.objects.filter(agent_id=gateway.agent_id, name=module_name).exists()


def _effective_command_payload(
    gateway: Gateway,
    command: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    effective = dict(payload or {})
    if command == "tailscale_up":
        if effective.get("tenant_id") is not None:
            from gateways.tailscale import build_tailscale_up_payload
            from gateways.validators import validate_cidr_list

            tenant_id = str(effective.pop("tenant_id"))
            advertise_routes = list(effective.pop("advertise_routes", []))
            force_reauth = effective.pop("force_reauth", True)
            accept_dns = effective.pop("accept_dns", True)
            reset = effective.pop("reset", True)
            validated_routes = validate_cidr_list(advertise_routes)
            return build_tailscale_up_payload(
                gateway,
                tenant_id=tenant_id,
                advertise_routes=validated_routes,
                force_reauth=force_reauth,
                accept_dns=accept_dns,
                reset=reset,
            )
        effective["custom_tags"] = list(gateway.custom_tags)
    return effective


def sync_gateway_routes(gateway: Gateway) -> dict[str, Any]:
    """Stub Headscale route sync for gateway routes UI."""
    node_id = gateway.tailscale_node_id or str(gateway.id)[:8]
    return {
        "routes": [
            {
                "cidr": "10.0.0.0/24",
                "approved": True,
                "enabled": True,
                "node_id": node_id,
            },
            {
                "cidr": "192.168.1.0/24",
                "approved": False,
                "enabled": False,
                "node_id": node_id,
            },
        ],
    }


def enqueue_gateway_command(
    gateway: Gateway,
    command: str,
    payload: dict[str, Any] | None = None,
) -> AgentCommand:
    if gateway.agent_id is None:
        msg = "Gateway has no enrolled agent"
        raise ValueError(msg)

    if command not in GATEWAY_COMMANDS:
        msg = f"Unsupported gateway command: {command}"
        raise ValueError(msg)

    if command in TAILSCALE_COMMANDS and not _gateway_has_module(gateway, "tailscale"):
        msg = "tailscale module is not installed on this gateway"
        raise ValueError(msg)

    return AgentCommand.objects.create(
        agent_id=gateway.agent_id,
        command=command,
        payload=_effective_command_payload(gateway, command, payload),
    )


@transaction.atomic
def delete_gateway(gateway: Gateway) -> None:
    """Remove gateway record and revoke its enrolled agent."""
    agent = gateway.agent
    gateway.delete()
    if agent is not None:
        AgentCommand.objects.filter(agent=agent).delete()
        AgentModule.objects.filter(agent=agent).delete()
        agent.delete()


def get_latest_scan_command(gateway: Gateway, scan_mode: str | None = None) -> AgentCommand | None:
    """Most recent scan_network command, optionally filtered by payload mode."""
    if gateway.agent_id is None:
        return None
    queryset = AgentCommand.objects.filter(
        agent_id=gateway.agent_id,
        command="scan_network",
    )
    if scan_mode is not None:
        queryset = queryset.filter(payload__mode=scan_mode)
    return queryset.order_by("-created_at").first()


def get_latest_acked_scan_command(gateway: Gateway) -> AgentCommand | None:
    from gateways.tailscale import get_latest_acked_scan_command as _get_latest_acked_scan_command

    return _get_latest_acked_scan_command(gateway)
