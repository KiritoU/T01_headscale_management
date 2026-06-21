from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from agents.models import AgentCommand, CommandState
from gateways.models import (
    AlertType,
    DiscoveredHost,
    Gateway,
    GatewayMonitorPolicy,
    GatewayStatus,
    MonitorAlert,
    ScanSnapshot,
    VulnFinding,
)
from gateways.module_service import (
    can_enqueue_discovery,
    can_enqueue_vuln_scan,
    discovery_required_modules,
    modules_ready,
    pending_network_scan,
    required_modules,
    vuln_modules_required,
    vuln_scan_modules,
)
from gateways.monitoring_policy import (
    SCAN_STRATEGY_FULL,
    build_interval_info,
    plan_full_sweep,
    plan_rotating_chunks,
    policy_config_from_model,
)
from gateways.services import enqueue_gateway_command

logger = logging.getLogger(__name__)


class MonitorScanTriggerError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _parse_scan_logs(command: AgentCommand) -> dict[str, Any] | None:
    result = command.result or {}
    logs = result.get("logs")
    if not logs:
        return None
    if isinstance(logs, dict):
        return logs
    try:
        return json.loads(logs)
    except (TypeError, json.JSONDecodeError):
        logger.warning("invalid scan logs for command %s", command.id)
        return None


def _extract_hosts_from_scan(body: dict[str, Any]) -> list[dict[str, Any]]:
    hosts: list[dict[str, Any]] = []
    for subnet in body.get("subnets", []):
        for host in subnet.get("hosts", []):
            ip = str(host.get("ip", "")).strip()
            if not ip:
                continue
            raw_ports = host.get("open_ports") or []
            open_ports = sorted(
                {
                    int(port)
                    for port in raw_ports
                    if str(port).isdigit() and int(port) > 0
                },
            )
            hosts.append(
                {
                    "ip": ip,
                    "hostname": str(host.get("hostname", "")),
                    "mac": str(host.get("mac", "")),
                    "open_ports": open_ports,
                },
            )
    return hosts


@transaction.atomic
def process_monitor_scan_ack(command: AgentCommand) -> None:
    if command.command != "scan_network":
        return
    payload = command.payload or {}
    if payload.get("mode") != "monitor":
        return
    if command.state != CommandState.ACKED:
        return

    if ScanSnapshot.objects.filter(command=command).exists():
        return

    body = _parse_scan_logs(command)
    if body is None:
        return

    gateway = Gateway.objects.filter(agent_id=command.agent_id).first()
    if gateway is None:
        return

    scanned_at = command.acked_at or timezone.now()
    chunk_cidrs = list(payload.get("targets") or [])
    hosts = _extract_hosts_from_scan(body)
    summary = body.get("summary") or {}

    ScanSnapshot.objects.create(
        gateway=gateway,
        command=command,
        scanned_at=scanned_at,
        chunk_cidrs=chunk_cidrs,
        host_count=len(hosts),
        summary=summary,
    )

    seen_ips: set[str] = set()
    for host in hosts:
        ip = host["ip"]
        seen_ips.add(ip)
        existing = DiscoveredHost.objects.filter(gateway=gateway, ip=ip).first()
        if existing is None:
            DiscoveredHost.objects.create(
                gateway=gateway,
                ip=ip,
                hostname=host["hostname"],
                mac=host["mac"],
                first_seen_at=scanned_at,
                last_seen_at=scanned_at,
                is_new=True,
                open_ports=host["open_ports"],
            )
            MonitorAlert.objects.create(
                gateway=gateway,
                alert_type=AlertType.NEW_HOST,
                host_ip=ip,
                message=f"New host discovered: {ip}",
            )
            continue

        DiscoveredHost.objects.filter(pk=existing.pk).update(
            hostname=host["hostname"] or existing.hostname,
            mac=host["mac"] or existing.mac,
            last_seen_at=scanned_at,
            is_new=False,
            open_ports=sorted(
                set(existing.open_ports or []) | set(host["open_ports"]),
            ),
        )

    _maybe_enqueue_vuln_scans(gateway, seen_ips)


def _maybe_enqueue_vuln_scans(gateway: Gateway, seen_ips: set[str]) -> None:
    try:
        policy = gateway.monitor_policy
    except GatewayMonitorPolicy.DoesNotExist:
        return

    if not can_enqueue_vuln_scan(gateway, policy):
        return

    stale_before = timezone.now() - timedelta(days=policy.vuln_rescan_days)
    hosts = DiscoveredHost.objects.filter(gateway=gateway, ip__in=seen_ips)
    pending_ids: list[Any] = []
    for host in hosts:
        if host.vuln_scan_pending:
            continue
        if host.is_new:
            pending_ids.append(host.pk)
            continue
        if host.last_vuln_scan_at is None or host.last_vuln_scan_at <= stale_before:
            pending_ids.append(host.pk)

    if not pending_ids:
        return

    DiscoveredHost.objects.filter(pk__in=pending_ids).update(vuln_scan_pending=True)


def get_vuln_scan_queue(agent) -> dict[str, Any]:
    gateway = Gateway.objects.filter(agent_id=agent.id).select_related("monitor_policy").first()
    if gateway is None:
        return {"parallel_workers": 1, "targets": []}

    try:
        policy = gateway.monitor_policy
    except GatewayMonitorPolicy.DoesNotExist:
        return {"parallel_workers": 1, "targets": []}

    parallel_workers = max(1, policy.vuln_parallel_workers)
    if not policy.vuln_scan_enabled:
        return {"parallel_workers": parallel_workers, "targets": []}
    if not modules_ready(gateway, vuln_modules_required(policy)):
        return {"parallel_workers": parallel_workers, "targets": []}

    modules = vuln_scan_modules(gateway, policy)
    pending_hosts = (
        DiscoveredHost.objects.filter(gateway=gateway, vuln_scan_pending=True)
        .order_by("first_seen_at")
        [:parallel_workers]
    )
    targets = [
        {
            "job_id": str(host.id),
            "ip": host.ip,
            "modules": modules,
            "open_ports": list(host.open_ports or []),
        }
        for host in pending_hosts
    ]
    return {"parallel_workers": parallel_workers, "targets": targets}


@transaction.atomic
def process_vuln_results_push(agent, payload: dict[str, Any]) -> None:
    gateway = Gateway.objects.filter(agent_id=agent.id).first()
    if gateway is None:
        return

    job_id = str(payload.get("job_id", "")).strip()
    ip = str(payload.get("ip", "")).strip()
    if not job_id and not ip:
        return

    host_query = DiscoveredHost.objects.filter(gateway=gateway)
    if job_id:
        host = host_query.filter(pk=job_id).first()
    else:
        host = host_query.filter(ip=ip).first()
    if host is None:
        return

    scanned_at = timezone.now()
    for finding in payload.get("findings") or []:
        finding_ip = str(finding.get("ip", "")).strip() or host.ip
        if finding_ip != host.ip:
            continue
        finding_id = str(finding.get("finding_id", ""))
        if finding_id and VulnFinding.objects.filter(
            discovered_host=host,
            finding_id=finding_id,
        ).exists():
            continue
        VulnFinding.objects.create(
            discovered_host=host,
            source=str(finding.get("source", "unknown")),
            severity=str(finding.get("severity", "info")),
            title=str(finding.get("title", "Finding")),
            finding_id=finding_id,
            details=dict(finding.get("details") or {}),
            found_at=scanned_at,
        )

    DiscoveredHost.objects.filter(pk=host.pk).update(
        vuln_scan_pending=False,
        last_vuln_scan_at=scanned_at,
    )


@transaction.atomic
def process_vuln_scan_ack(command: AgentCommand) -> None:
    if command.command != "vuln_scan":
        return
    if command.state != CommandState.ACKED:
        return

    gateway = Gateway.objects.filter(agent_id=command.agent_id).first()
    if gateway is None:
        return

    body = _parse_scan_logs(command)
    if body is None:
        return

    scanned_at = command.acked_at or timezone.now()
    targets = list((command.payload or {}).get("targets") or [])

    for finding in body.get("findings", []):
        ip = str(finding.get("ip", "")).strip()
        if not ip:
            continue
        host = DiscoveredHost.objects.filter(gateway=gateway, ip=ip).first()
        if host is None:
            continue
        finding_id = str(finding.get("finding_id", ""))
        if finding_id and VulnFinding.objects.filter(
            discovered_host=host,
            finding_id=finding_id,
        ).exists():
            continue
        VulnFinding.objects.create(
            discovered_host=host,
            source=str(finding.get("source", "unknown")),
            severity=str(finding.get("severity", "info")),
            title=str(finding.get("title", "Finding")),
            finding_id=finding_id,
            details=dict(finding.get("details") or {}),
            found_at=scanned_at,
        )

    if targets:
        DiscoveredHost.objects.filter(gateway=gateway, ip__in=targets).update(
            last_vuln_scan_at=scanned_at,
        )


def _policy_due(policy: GatewayMonitorPolicy, now) -> bool:
    if not policy.enabled:
        return False
    if policy.last_scheduled_at is None:
        return True
    delta = timedelta(minutes=policy.discover_interval_minutes)
    return policy.last_scheduled_at + delta <= now


def _plan_targets(policy: GatewayMonitorPolicy) -> tuple[tuple[str, ...], int]:
    cidrs = list(policy.monitored_cidrs or [])
    if policy.scan_strategy == SCAN_STRATEGY_FULL:
        plan = plan_full_sweep(cidrs)
        capped = plan.targets[: policy.chunk_count]
        return capped, plan.next_cursor

    plan = plan_rotating_chunks(
        cidrs,
        chunk_count=policy.chunk_count,
        chunk_cursor=policy.chunk_cursor,
    )
    return plan.targets, plan.next_cursor


@transaction.atomic
def schedule_policy_scan(policy: GatewayMonitorPolicy, *, now=None) -> AgentCommand | None:
    now = now or timezone.now()
    policy = (
        GatewayMonitorPolicy.objects.select_for_update()
        .select_related("gateway", "gateway__agent")
        .get(pk=policy.pk)
    )
    gateway = policy.gateway

    if gateway.status != GatewayStatus.ONLINE or gateway.agent_id is None:
        return None
    if not _policy_due(policy, now):
        return None
    if not can_enqueue_discovery(gateway):
        return None

    targets, next_cursor = _plan_targets(policy)
    if not targets:
        return None

    command = enqueue_gateway_command(
        gateway,
        "scan_network",
        {"mode": "monitor", "targets": list(targets)},
    )
    GatewayMonitorPolicy.objects.filter(pk=policy.pk).update(
        chunk_cursor=next_cursor,
        last_scheduled_at=now,
    )
    return command


@transaction.atomic
def trigger_immediate_monitor_scan(gateway: Gateway) -> AgentCommand:
    """Enqueue the next monitor chunk immediately, bypassing the schedule interval."""
    policy = get_or_create_monitor_policy(gateway)

    if gateway.status != GatewayStatus.ONLINE or gateway.agent_id is None:
        raise MonitorScanTriggerError(
            "Gateway must be online with an enrolled agent",
        )

    if not modules_ready(gateway, discovery_required_modules()):
        raise MonitorScanTriggerError(
            "Masscan module is not installed or still installing",
        )

    if pending_network_scan(gateway):
        raise MonitorScanTriggerError(
            "A network scan is already queued or running",
            status_code=409,
        )

    targets, next_cursor = _plan_targets(policy)
    if not targets:
        raise MonitorScanTriggerError(
            "No scan targets configured in monitoring policy",
        )

    now = timezone.now()
    command = enqueue_gateway_command(
        gateway,
        "scan_network",
        {"mode": "monitor", "targets": list(targets)},
    )
    GatewayMonitorPolicy.objects.filter(pk=policy.pk).update(
        chunk_cursor=next_cursor,
        last_scheduled_at=now,
    )
    return command


def trigger_vuln_rescan(gateway: Gateway, *, ip: str | None = None) -> dict[str, Any]:
    """Mark discovered hosts for immediate vuln scanning on the next agent poll."""
    policy = get_or_create_monitor_policy(gateway)

    if gateway.status != GatewayStatus.ONLINE or gateway.agent_id is None:
        raise MonitorScanTriggerError(
            "Gateway must be online with an enrolled agent",
        )

    if not policy.vuln_scan_enabled:
        raise MonitorScanTriggerError("Vulnerability scanning is disabled on this gateway")

    if not modules_ready(gateway, vuln_modules_required(policy)):
        raise MonitorScanTriggerError(
            "Required vuln scan modules are not installed yet",
        )

    hosts = DiscoveredHost.objects.filter(gateway=gateway)
    if ip:
        normalized_ip = ip.strip()
        if not normalized_ip:
            raise MonitorScanTriggerError("IP address cannot be empty")
        hosts = hosts.filter(ip=normalized_ip)
        if not hosts.exists():
            raise MonitorScanTriggerError(
                f"No discovered host with IP {normalized_ip}",
                status_code=404,
            )

    host_ips = list(hosts.values_list("ip", flat=True))
    if not host_ips:
        raise MonitorScanTriggerError("No discovered hosts to queue for vuln rescan")

    updated = hosts.update(vuln_scan_pending=True)
    return {"queued_count": updated, "hosts": host_ips}


def run_monitor_scheduler() -> int:
    now = timezone.now()
    scheduled = 0
    policy_ids = list(
        GatewayMonitorPolicy.objects.filter(enabled=True)
        .values_list("pk", flat=True)
        .order_by("gateway_id"),
    )
    for policy_id in policy_ids:
        policy = GatewayMonitorPolicy.objects.select_related(
            "gateway",
            "gateway__agent",
        ).get(pk=policy_id)
        if schedule_policy_scan(policy, now=now) is not None:
            scheduled += 1
    logger.info("run_monitor_scheduler: scheduled %d scans", scheduled)
    return scheduled


def get_or_create_monitor_policy(gateway: Gateway) -> GatewayMonitorPolicy:
    policy, _created = GatewayMonitorPolicy.objects.get_or_create(
        gateway=gateway,
    )
    return policy


def build_policy_response(policy: GatewayMonitorPolicy) -> dict[str, Any]:
    config = policy_config_from_model(policy)
    interval = build_interval_info(config)
    gateway = policy.gateway
    modules = list(discovery_required_modules())
    if policy.vuln_scan_enabled:
        for name in required_modules(policy, include_optional=True):
            if name not in modules:
                modules.append(name)
    from gateways.module_service import module_statuses

    return {
        "enabled": policy.enabled,
        "monitored_cidrs": list(policy.monitored_cidrs or []),
        "scan_strategy": policy.scan_strategy,
        "chunk_count": policy.chunk_count,
        "discover_interval_minutes": policy.discover_interval_minutes,
        "vuln_rescan_days": policy.vuln_rescan_days,
        "vuln_scan_enabled": policy.vuln_scan_enabled,
        "vuln_modules": list(policy.vuln_modules or []),
        "nuclei_enabled": policy.nuclei_enabled,
        "vuln_parallel_workers": policy.vuln_parallel_workers,
        "chunk_cursor": policy.chunk_cursor,
        "last_scheduled_at": (
            policy.last_scheduled_at.isoformat() if policy.last_scheduled_at else None
        ),
        "min_interval_minutes": interval.min_interval_minutes,
        "full_coverage_hours": interval.full_coverage_hours,
        "module_statuses": module_statuses(gateway, modules),
    }
