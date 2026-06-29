from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone

from agents.models import Agent, ResourceSample


def resource_sample_retention_seconds() -> int:
    return int(getattr(settings, "RESOURCE_SAMPLE_RETENTION_SECONDS", 6 * 60 * 60))


def record_resource_sample(
    agent: Agent,
    metrics: dict[str, Any],
    *,
    sampled_at=None,
) -> ResourceSample:
    now = sampled_at or timezone.now()
    sample = ResourceSample.objects.create(
        agent=agent,
        sampled_at=now,
        cpu_percent=metrics.get("cpu_percent"),
        mem_percent=metrics.get("mem_percent"),
        disk_percent=metrics.get("disk_percent"),
        mem_total_bytes=metrics.get("mem_total_bytes"),
        mem_used_bytes=metrics.get("mem_used_bytes"),
        disk_total_bytes=metrics.get("disk_total_bytes"),
        disk_used_bytes=metrics.get("disk_used_bytes"),
        net_rx_bytes_per_sec=metrics.get("net_rx_bytes_per_sec"),
        net_tx_bytes_per_sec=metrics.get("net_tx_bytes_per_sec"),
        load_avg_1m=metrics.get("load_avg_1m"),
        cpu_count=metrics.get("cpu_count"),
        uptime_seconds=metrics.get("uptime_seconds"),
    )
    cutoff = now - timedelta(seconds=resource_sample_retention_seconds())
    ResourceSample.objects.filter(agent=agent, sampled_at__lt=cutoff).delete()
    return sample


def list_resource_samples(
    agent: Agent,
    *,
    window_seconds: int | None = None,
) -> list[ResourceSample]:
    retention = resource_sample_retention_seconds()
    window = min(window_seconds or retention, retention)
    since = timezone.now() - timedelta(seconds=window)
    return list(
        ResourceSample.objects.filter(agent=agent, sampled_at__gte=since).order_by("sampled_at"),
    )


def latest_resource_sample(agent: Agent) -> ResourceSample | None:
    return ResourceSample.objects.filter(agent=agent).order_by("-sampled_at").first()


def build_metrics_response(
    agent: Agent | None,
    *,
    window_seconds: int | None = None,
) -> dict[str, Any]:
    from agents.serializers import ResourceSampleSerializer

    retention = resource_sample_retention_seconds()
    window = min(window_seconds or retention, retention)
    if agent is None:
        return {
            "current": None,
            "samples": [],
            "window_seconds": window,
        }

    samples = list_resource_samples(agent, window_seconds=window)
    current = samples[-1] if samples else latest_resource_sample(agent)
    serializer = ResourceSampleSerializer(samples, many=True)
    current_data = ResourceSampleSerializer(current).data if current else None
    return {
        "current": current_data,
        "samples": serializer.data,
        "window_seconds": window,
    }


def parse_metrics_window_param(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value
