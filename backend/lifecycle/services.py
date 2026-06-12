from __future__ import annotations

from dataclasses import dataclass

from agents.models import Agent, AgentCommand, CommandState
from agents.services import EnqueuedCommand, enqueue_command
from tenants.models import BootstrapStatus, Tenant

_LIFECYCLE_COMMANDS = frozenset({"verify_tenant", "bootstrap_tenant"})
_PENDING_STATES = (CommandState.PENDING, CommandState.DISPATCHED)


class TenantLifecycleError(Exception):
    """Raised when a tenant lifecycle operation cannot be performed."""


@dataclass(frozen=True)
class TenantCommandPayload:
    tenant_id: str
    tenant_slug: str
    headscale_host: str
    headplane_host: str
    db_name: str


def _tenant_command_payload(tenant: Tenant) -> TenantCommandPayload:
    return TenantCommandPayload(
        tenant_id=str(tenant.id),
        tenant_slug=tenant.slug,
        headscale_host=tenant.headscale_host,
        headplane_host=tenant.headplane_host,
        db_name=tenant.db_name,
    )


def _resolve_worker_agent(tenant: Tenant) -> Agent:
    if tenant.worker_id is None:
        msg = "Tenant has no assigned worker."
        raise TenantLifecycleError(msg)
    worker = tenant.worker
    if worker is None or worker.agent_id is None:
        msg = "Worker has no registered agent."
        raise TenantLifecycleError(msg)
    return worker.agent


def _bootstrap_output_ref(tenant: Tenant) -> str:
    return f"worker-output://{tenant.worker_id}/tenants/{tenant.slug}/bootstrap"


def _find_pending_lifecycle_command(
    agent: Agent,
    tenant_id: str,
    command: str,
) -> AgentCommand | None:
    if command not in _LIFECYCLE_COMMANDS:
        return None
    return (
        AgentCommand.objects.filter(
            agent=agent,
            command=command,
            state__in=_PENDING_STATES,
            payload__tenant_id=tenant_id,
        )
        .order_by("-created_at")
        .first()
    )


def _to_enqueued_command(command: AgentCommand, *, skipped: bool = False) -> EnqueuedCommand:
    return EnqueuedCommand(
        id=str(command.id),
        command=command.command,
        payload=dict(command.payload),
        state=command.state,
        created_at=command.created_at.isoformat(),
        skipped=skipped,
    )


def enqueue_verify_tenant(tenant: Tenant) -> EnqueuedCommand:
    agent = _resolve_worker_agent(tenant)
    payload = _tenant_command_payload(tenant)
    existing = _find_pending_lifecycle_command(agent, payload.tenant_id, "verify_tenant")
    if existing is not None:
        return _to_enqueued_command(existing, skipped=True)

    return enqueue_command(
        agent,
        command="verify_tenant",
        payload={
            "tenant_id": payload.tenant_id,
            "tenant_slug": payload.tenant_slug,
            "headscale_host": payload.headscale_host,
            "headplane_host": payload.headplane_host,
        },
    )


def enqueue_bootstrap_tenant(tenant: Tenant) -> EnqueuedCommand:
    agent = _resolve_worker_agent(tenant)
    payload = _tenant_command_payload(tenant)

    if tenant.bootstrap_status == BootstrapStatus.BOOTSTRAPPED:
        return EnqueuedCommand(
            id=None,
            command=None,
            payload={},
            state=None,
            created_at=None,
            skipped=True,
            bootstrap_output_ref=tenant.bootstrap_output_ref,
            bootstrap_status=tenant.bootstrap_status,
        )

    existing = _find_pending_lifecycle_command(agent, payload.tenant_id, "bootstrap_tenant")
    if existing is not None:
        return EnqueuedCommand(
            id=str(existing.id),
            command=existing.command,
            payload=dict(existing.payload),
            state=existing.state,
            created_at=existing.created_at.isoformat(),
            skipped=True,
            bootstrap_output_ref=tenant.bootstrap_output_ref,
            bootstrap_status=tenant.bootstrap_status,
        )

    output_ref = _bootstrap_output_ref(tenant)
    command = enqueue_command(
        agent,
        command="bootstrap_tenant",
        payload={
            "tenant_id": payload.tenant_id,
            "tenant_slug": payload.tenant_slug,
            "headscale_host": payload.headscale_host,
            "headplane_host": payload.headplane_host,
            "db_name": payload.db_name,
            "output_ref": output_ref,
        },
    )
    Tenant.objects.filter(pk=tenant.pk).update(
        bootstrap_status=BootstrapStatus.PROVISIONING,
        bootstrap_output_ref=output_ref,
    )
    return EnqueuedCommand(
        id=command.id,
        command=command.command,
        payload=command.payload,
        state=command.state,
        created_at=command.created_at,
        skipped=False,
        bootstrap_output_ref=output_ref,
        bootstrap_status=BootstrapStatus.PROVISIONING,
    )
