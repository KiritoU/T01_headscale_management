from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count

from django.conf import settings

from agents.liveness import refresh_worker_liveness
from agents.models import Agent, AgentCommand, CommandState
from agents.services import EnqueuedCommand, enqueue_command
from core.edge_settings import validate_production_edge_config
from dns.services import DnsConfigurationError, ensure_tenant_dns, remove_tenant_dns
from lifecycle.deployment import tenant_production_mode
from lifecycle.identifiers import validate_db_name, validate_suffix
from lifecycle.provision_payload import build_provision_payload
from lifecycle.services import TenantLifecycleError, enqueue_bootstrap_tenant
from tenants.detail import persist_bootstrap_secrets, record_health_from_verify
from tenants.legacy import legacy_tenant_metadata
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant
from workers.models import Worker, WorkerStatus

_RUNTIME_COMMANDS = frozenset(
    {"provision_tenant", "start_tenant", "stop_tenant", "deprovision_tenant"},
)
_BOOTSTRAP_COMMANDS = frozenset({"bootstrap_tenant"})
_TENANT_SYNC_COMMANDS = _RUNTIME_COMMANDS | _BOOTSTRAP_COMMANDS
_PENDING_STATES = (CommandState.PENDING, CommandState.DISPATCHED)


class WorkerTenantError(Exception):
    """Raised when a worker-scoped tenant operation cannot be performed."""


@dataclass(frozen=True)
class TenantSummary:
    total: int
    bootstrap_status: dict[str, int]
    runtime_status: dict[str, int]


@dataclass(frozen=True)
class TenantRemovalResult:
    removed_immediately: bool
    command: EnqueuedCommand | None = None


def assert_worker_ready(worker: Worker) -> None:
    worker = refresh_worker_liveness(worker)
    if worker.status != WorkerStatus.ONLINE:
        msg = "Worker is not online."
        raise WorkerTenantError(msg)
    if not worker.docker_reachable:
        msg = "Worker Docker is not reachable."
        raise WorkerTenantError(msg)
    if worker.agent_id is None:
        msg = "Worker has no registered agent."
        raise WorkerTenantError(msg)


def _resolve_worker_agent(worker: Worker) -> Agent:
    assert_worker_ready(worker)
    if worker.agent is None:
        msg = "Worker has no registered agent."
        raise WorkerTenantError(msg)
    return worker.agent


def _resolve_worker_agent_for_enqueue(worker: Worker) -> Agent:
    if worker.agent_id is None or worker.agent is None:
        msg = "Worker has no registered agent."
        raise WorkerTenantError(msg)
    return worker.agent


def _tenant_worker_or_error(worker: Worker, tenant: Tenant) -> None:
    if tenant.worker_id != worker.id:
        msg = "Tenant is not assigned to this worker."
        raise WorkerTenantError(msg)


def _reject_if_deleting(tenant: Tenant) -> None:
    if tenant.runtime_status == RuntimeStatus.DELETING:
        msg = "Tenant is being removed."
        raise WorkerTenantError(msg)


def _assert_worker_production_consistency(worker: Worker, production: bool) -> None:
    for tenant in Tenant.objects.filter(worker=worker):
        existing = tenant_production_mode(tenant.desired_config)
        if existing != production:
            msg = (
                "Cannot mix production and dev tenants on one worker. "
                "Use a separate worker for a different deployment mode."
            )
            raise WorkerTenantError(msg)


def _provision_command_payload(tenant: Tenant) -> dict[str, Any]:
    payload = build_provision_payload(tenant)
    payload["config_ref"] = f"worker-config://{tenant.worker_id}/tenants/{tenant.slug}"
    return payload


def _find_pending_runtime_command(
    agent: Agent,
    tenant_id: str,
    command: str,
) -> AgentCommand | None:
    if command not in _RUNTIME_COMMANDS:
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


@transaction.atomic
def bulk_create_tenants(
    worker: Worker,
    *,
    suffix: str,
    start_number: int | None = None,
    count: int | None = None,
    base_domain: str,
    production: bool = False,
    description: str = "",
) -> list[Tenant]:
    try:
        validate_suffix(suffix)
    except ValueError as exc:
        raise WorkerTenantError(str(exc)) from exc
    _assert_worker_production_consistency(worker, production)

    planned: list[dict[str, Any]] = []
    if count is None:
        metadata = legacy_tenant_metadata(
            suffix=suffix,
            number=None,
            base_domain=base_domain,
            production=production,
        )
        slug = metadata["slug"]
        if Tenant.objects.filter(slug=slug).exists():
            msg = f"Tenant slug already exists: {slug}"
            raise WorkerTenantError(msg)
        planned.append(metadata)
    else:
        if start_number is None:
            msg = "Start number is required when creating multiple tenants."
            raise WorkerTenantError(msg)
        for number in range(start_number, start_number + count):
            metadata = legacy_tenant_metadata(
                suffix=suffix,
                number=number,
                base_domain=base_domain,
                production=production,
            )
            slug = metadata["slug"]
            if Tenant.objects.filter(slug=slug).exists():
                msg = f"Tenant slug already exists: {slug}"
                raise WorkerTenantError(msg)
            planned.append(metadata)

    tenants: list[Tenant] = []
    try:
        for metadata in planned:
            tenant = Tenant.objects.create(
                slug=metadata["slug"],
                headscale_host=metadata["headscale_host"],
                headplane_host=metadata["headplane_host"],
                db_name=metadata["db_name"],
                desired_config=metadata["desired_config"],
                description=description.strip(),
                worker=worker,
                runtime_status=RuntimeStatus.PENDING,
            )
            tenants.append(tenant)
    except IntegrityError as exc:
        msg = "Tenant slug or database name already exists"
        raise WorkerTenantError(msg) from exc
    return tenants


def remove_tenant(worker: Worker, tenant: Tenant) -> TenantRemovalResult:
    _tenant_worker_or_error(worker, tenant)
    tenant.refresh_from_db()

    if tenant.runtime_status == RuntimeStatus.PENDING:
        remove_tenant_dns(tenant)
        tenant.delete()
        return TenantRemovalResult(removed_immediately=True)

    if tenant.runtime_status == RuntimeStatus.DELETING:
        command = enqueue_deprovision_tenant(tenant)
        return TenantRemovalResult(removed_immediately=False, command=command)

    command = enqueue_deprovision_tenant(tenant)
    Tenant.objects.filter(pk=tenant.pk).update(runtime_status=RuntimeStatus.DELETING)
    return TenantRemovalResult(removed_immediately=False, command=command)


def enqueue_deprovision_tenant(tenant: Tenant) -> EnqueuedCommand:
    if tenant.worker_id is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)
    worker = tenant.worker
    if worker is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)

    agent = _resolve_worker_agent_for_enqueue(worker)
    tenant_id = str(tenant.id)
    existing = _find_pending_runtime_command(agent, tenant_id, "deprovision_tenant")
    if existing is not None:
        return _to_enqueued_command(existing, skipped=True)

    shared_edge_docker_network = ""
    if worker.shared_edge_traefik:
        shared_edge_docker_network = settings.SHARED_EDGE_DOCKER_NETWORK

    command = enqueue_command(
        agent,
        command="deprovision_tenant",
        payload={
            "tenant_id": tenant_id,
            "tenant_slug": tenant.slug,
            "db_name": tenant.db_name,
            "shared_edge_docker_network": shared_edge_docker_network,
        },
    )
    return command


def enqueue_provision_tenant(tenant: Tenant) -> EnqueuedCommand:
    if tenant.worker_id is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)
    _reject_if_deleting(tenant)
    worker = tenant.worker
    if worker is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)

    try:
        validate_db_name(tenant.db_name)
    except ValueError as exc:
        raise WorkerTenantError(str(exc)) from exc
    _assert_worker_production_consistency(
        worker,
        tenant_production_mode(tenant.desired_config),
    )
    try:
        validate_production_edge_config(
            worker,
            production=tenant_production_mode(tenant.desired_config),
        )
    except ValueError as exc:
        raise WorkerTenantError(str(exc)) from exc

    agent = _resolve_worker_agent(worker)
    tenant_id = str(tenant.id)
    existing = _find_pending_runtime_command(agent, tenant_id, "provision_tenant")
    if existing is not None:
        return _to_enqueued_command(existing, skipped=True)

    try:
        ensure_tenant_dns(tenant)
    except DnsConfigurationError as exc:
        raise WorkerTenantError(str(exc)) from exc

    command = enqueue_command(
        agent,
        command="provision_tenant",
        payload=_provision_command_payload(tenant),
    )
    Tenant.objects.filter(pk=tenant.pk).update(runtime_status=RuntimeStatus.PROVISIONING)
    return command


def enqueue_start_tenant(tenant: Tenant) -> EnqueuedCommand:
    if tenant.worker_id is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)
    _reject_if_deleting(tenant)
    worker = tenant.worker
    if worker is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)

    agent = _resolve_worker_agent(worker)
    tenant_id = str(tenant.id)
    existing = _find_pending_runtime_command(agent, tenant_id, "start_tenant")
    if existing is not None:
        return _to_enqueued_command(existing, skipped=True)

    return enqueue_command(
        agent,
        command="start_tenant",
        payload={
            "tenant_id": tenant_id,
            "tenant_slug": tenant.slug,
            "headscale_host": tenant.headscale_host,
            "headplane_host": tenant.headplane_host,
        },
    )


def enqueue_stop_tenant(tenant: Tenant) -> EnqueuedCommand:
    if tenant.worker_id is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)
    _reject_if_deleting(tenant)
    worker = tenant.worker
    if worker is None:
        msg = "Tenant has no assigned worker."
        raise WorkerTenantError(msg)

    agent = _resolve_worker_agent(worker)
    tenant_id = str(tenant.id)
    existing = _find_pending_runtime_command(agent, tenant_id, "stop_tenant")
    if existing is not None:
        return _to_enqueued_command(existing, skipped=True)

    return enqueue_command(
        agent,
        command="stop_tenant",
        payload={
            "tenant_id": tenant_id,
            "tenant_slug": tenant.slug,
            "headscale_host": tenant.headscale_host,
            "headplane_host": tenant.headplane_host,
        },
    )


def bulk_provision_pending_tenants(worker: Worker) -> list[EnqueuedCommand]:
    assert_worker_ready(worker)
    pending = Tenant.objects.filter(
        worker=worker,
        runtime_status=RuntimeStatus.PENDING,
    ).order_by("slug")
    return [enqueue_provision_tenant(tenant) for tenant in pending]


def get_tenant_summary(worker: Worker) -> TenantSummary:
    tenants = Tenant.objects.filter(worker=worker)
    bootstrap_counts = {status: 0 for status in BootstrapStatus.values}
    runtime_counts = {status: 0 for status in RuntimeStatus.values}

    for row in tenants.values("bootstrap_status").annotate(count=Count("id")):
        bootstrap_counts[row["bootstrap_status"]] = row["count"]

    for row in tenants.values("runtime_status").annotate(count=Count("id")):
        runtime_counts[row["runtime_status"]] = row["count"]

    return TenantSummary(
        total=tenants.count(),
        bootstrap_status=bootstrap_counts,
        runtime_status=runtime_counts,
    )


def sync_tenant_from_acked_command(command: AgentCommand) -> None:
    """Apply tenant status fields when a worker agent acknowledges a command."""
    if command.command not in _TENANT_SYNC_COMMANDS and command.command != "verify_tenant":
        return
    tenant_id = (command.payload or {}).get("tenant_id")
    if not tenant_id:
        return
    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return
    tenant = sync_tenant_runtime_from_command(command, tenant)
    if command.command == "verify_tenant":
        record_health_from_verify(command, tenant)
    maybe_enqueue_bootstrap_after_provision(command, tenant)


def maybe_enqueue_bootstrap_after_provision(command: AgentCommand, tenant: Tenant) -> None:
    """Queue bootstrap automatically after a successful provision."""
    if command.command != "provision_tenant":
        return
    if command.state != CommandState.ACKED:
        return

    result = dict(command.result or {})
    if result.get("runtime_status") != RuntimeStatus.RUNNING:
        return

    tenant.refresh_from_db()
    if tenant.bootstrap_status in {
        BootstrapStatus.BOOTSTRAPPED,
        BootstrapStatus.PROVISIONING,
    }:
        return

    try:
        enqueue_bootstrap_tenant(tenant)
    except TenantLifecycleError:
        return


def sync_tenant_runtime_from_command(command: AgentCommand, tenant: Tenant) -> Tenant:
    """Apply runtime_status from an acked command result."""
    command.refresh_from_db()
    if command.state not in {CommandState.ACKED, CommandState.FAILED}:
        return tenant

    if command.command == "deprovision_tenant":
        return _sync_deprovision_command(command, tenant)

    result = dict(command.result or {})
    runtime_status = result.get("runtime_status")
    if runtime_status in RuntimeStatus.values:
        Tenant.objects.filter(pk=tenant.pk).update(runtime_status=runtime_status)
    elif command.state == CommandState.FAILED and command.command in _RUNTIME_COMMANDS:
        Tenant.objects.filter(pk=tenant.pk).update(runtime_status=RuntimeStatus.FAILED)

    bootstrap_status = result.get("bootstrap_status")
    if bootstrap_status in BootstrapStatus.values:
        Tenant.objects.filter(pk=tenant.pk).update(bootstrap_status=bootstrap_status)
    elif command.state == CommandState.FAILED and command.command in _BOOTSTRAP_COMMANDS:
        Tenant.objects.filter(pk=tenant.pk).update(bootstrap_status=BootstrapStatus.FAILED)

    if command.command == "bootstrap_tenant" and command.state == CommandState.ACKED:
        persist_bootstrap_secrets(tenant, result.get("bootstrap"))

    tenant.refresh_from_db()
    return tenant


def _sync_deprovision_command(command: AgentCommand, tenant: Tenant) -> Tenant:
    if command.state == CommandState.ACKED:
        result = dict(command.result or {})
        if result.get("exit_code") == 0:
            remove_tenant_dns(tenant)
            tenant.delete()
            return tenant
        Tenant.objects.filter(pk=tenant.pk).update(runtime_status=RuntimeStatus.FAILED)
    elif command.state == CommandState.FAILED:
        Tenant.objects.filter(pk=tenant.pk).update(runtime_status=RuntimeStatus.FAILED)

    tenant.refresh_from_db()
    return tenant


def removal_result_to_action_data(result: TenantRemovalResult) -> dict[str, Any]:
    if result.command is None:
        return {}
    return {
        "command_id": result.command.id,
        "command": result.command.command,
        "state": result.command.state,
        "skipped": result.command.skipped,
        "runtime_status": RuntimeStatus.DELETING,
    }
