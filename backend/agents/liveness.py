"""Agent heartbeat liveness — mark workers/gateways offline when heartbeats stop."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from agents.models import Agent
from gateways.models import Gateway, GatewayStatus
from workers.models import Worker, WorkerStatus

# Match command stale expiry (poll_interval * 2) plus one poll cycle for jitter.
DEFAULT_OFFLINE_GRACE_MULTIPLIER = 3


def heartbeat_offline_cutoff(
    poll_interval_seconds: int,
    *,
    multiplier: int = DEFAULT_OFFLINE_GRACE_MULTIPLIER,
) -> timedelta:
    return timedelta(seconds=poll_interval_seconds * multiplier)


def is_heartbeat_stale(
    last_heartbeat_at,
    poll_interval_seconds: int,
    *,
    multiplier: int = DEFAULT_OFFLINE_GRACE_MULTIPLIER,
) -> bool:
    if last_heartbeat_at is None:
        return False
    cutoff = timezone.now() - heartbeat_offline_cutoff(
        poll_interval_seconds,
        multiplier=multiplier,
    )
    return last_heartbeat_at < cutoff


def _poll_interval_for_agent(agent: Agent | None) -> int:
    if agent is None:
        return 15
    return agent.poll_interval_seconds


def refresh_worker_liveness(worker: Worker) -> Worker:
    """Mark a single worker offline when its heartbeat is stale."""
    if worker.status != WorkerStatus.ONLINE or worker.agent_id is None:
        return worker

    poll_interval = _poll_interval_for_agent(worker.agent)
    if not is_heartbeat_stale(worker.last_heartbeat_at, poll_interval):
        return worker

    Worker.objects.filter(pk=worker.pk).update(
        status=WorkerStatus.OFFLINE,
        updated_at=timezone.now(),
    )
    worker.status = WorkerStatus.OFFLINE
    return worker


def refresh_gateway_liveness(gateway: Gateway) -> Gateway:
    """Mark a single gateway offline when its heartbeat is stale."""
    if gateway.status != GatewayStatus.ONLINE or gateway.agent_id is None:
        return gateway

    poll_interval = _poll_interval_for_agent(gateway.agent)
    if not is_heartbeat_stale(gateway.last_heartbeat_at, poll_interval):
        return gateway

    Gateway.objects.filter(pk=gateway.pk).update(
        status=GatewayStatus.OFFLINE,
        updated_at=timezone.now(),
    )
    gateway.status = GatewayStatus.OFFLINE
    return gateway


def mark_stale_workers_and_gateways_offline() -> tuple[int, int]:
    """Bulk-mark online workers/gateways offline when heartbeats are stale."""
    workers_updated = 0
    gateways_updated = 0

    for worker in Worker.objects.filter(status=WorkerStatus.ONLINE).select_related("agent"):
        before = worker.status
        refresh_worker_liveness(worker)
        if before != worker.status:
            workers_updated += 1

    for gateway in Gateway.objects.filter(status=GatewayStatus.ONLINE).select_related("agent"):
        before = gateway.status
        refresh_gateway_liveness(gateway)
        if before != gateway.status:
            gateways_updated += 1

    return workers_updated, gateways_updated
