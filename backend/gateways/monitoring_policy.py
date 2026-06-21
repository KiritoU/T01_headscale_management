from __future__ import annotations

import ipaddress
import math
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError

DEFAULT_MONITORED_CIDRS: tuple[str, ...] = ("192.168.0.0/16",)
BLOCKED_CIDRS: frozenset[str] = frozenset(
    {"10.0.0.0/8", "0.0.0.0/0", "172.16.0.0/12"},
)
MAX_CIDR_COUNT = 8
MAX_TOTAL_ADDRESSES = 65_536
ALLOWED_MIN_PREFIX = 16
ALLOWED_MAX_PREFIX = 28
SECONDS_PER_CHUNK = 12
SAFETY_MARGIN = 1.15
MIN_INTERVAL_FLOOR_MINUTES = 10

SCAN_STRATEGY_ROTATING = "rotating_chunks"
SCAN_STRATEGY_FULL = "full_sweep"


def default_monitored_cidrs() -> list[str]:
    return list(DEFAULT_MONITORED_CIDRS)


@dataclass(frozen=True)
class MonitorPolicyConfig:
    monitored_cidrs: tuple[str, ...]
    scan_strategy: str
    chunk_count: int
    discover_interval_minutes: int
    vuln_rescan_days: int = 1
    vuln_scan_enabled: bool = False
    vuln_modules: tuple[str, ...] = ()
    nuclei_enabled: bool = True
    chunk_cursor: int = 0


@dataclass(frozen=True)
class IntervalInfo:
    min_interval_minutes: int
    full_coverage_hours: float | None


@dataclass(frozen=True)
class ChunkPlan:
    targets: tuple[str, ...]
    next_cursor: int
    total_chunks: int


def normalize_monitored_cidrs(cidrs: list[str] | None) -> list[str]:
    if not cidrs:
        return list(DEFAULT_MONITORED_CIDRS)
    return [str(c).strip() for c in cidrs if str(c).strip()]


def validate_monitored_cidrs(
    cidrs: list[str] | None,
    *,
    allow_large_cidrs: bool = False,
) -> list[str]:
    normalized = normalize_monitored_cidrs(cidrs)
    if len(normalized) > MAX_CIDR_COUNT:
        raise ValidationError(f"At most {MAX_CIDR_COUNT} monitored CIDRs are allowed")

    validated: list[str] = []
    total_addresses = 0

    for cidr in normalized:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValidationError(f"Invalid CIDR '{cidr}': {exc}") from exc

        normalized_cidr = str(network)
        if normalized_cidr in BLOCKED_CIDRS and not allow_large_cidrs:
            raise ValidationError(
                f"CIDR {normalized_cidr} is not allowed without admin override",
            )

        if not allow_large_cidrs:
            if network.prefixlen < ALLOWED_MIN_PREFIX or network.prefixlen > ALLOWED_MAX_PREFIX:
                raise ValidationError(
                    f"CIDR prefix must be between /{ALLOWED_MIN_PREFIX} "
                    f"and /{ALLOWED_MAX_PREFIX}: {normalized_cidr}",
                )

        validated.append(normalized_cidr)
        total_addresses += network.num_addresses

    if total_addresses > MAX_TOTAL_ADDRESSES and not allow_large_cidrs:
        raise ValidationError(
            f"Total monitored addresses ({total_addresses}) exceeds "
            f"{MAX_TOTAL_ADDRESSES} without admin override",
        )

    return validated


def split_to_scan_chunks(cidr: str) -> list[str]:
    network = ipaddress.ip_network(cidr, strict=False)
    if network.prefixlen >= 24:
        return [str(network)]
    return [str(subnet) for subnet in network.subnets(new_prefix=24)]


def enumerate_all_chunks(monitored_cidrs: list[str]) -> list[str]:
    chunks: list[str] = []
    for cidr in monitored_cidrs:
        chunks.extend(split_to_scan_chunks(cidr))
    return chunks


def plan_rotating_chunks(
    monitored_cidrs: list[str],
    *,
    chunk_count: int,
    chunk_cursor: int,
) -> ChunkPlan:
    if chunk_count < 1:
        raise ValueError("chunk_count must be at least 1")

    all_chunks = enumerate_all_chunks(monitored_cidrs)
    total = len(all_chunks)
    if total == 0:
        return ChunkPlan(targets=(), next_cursor=0, total_chunks=0)

    cursor = chunk_cursor % total
    selected: list[str] = []
    for offset in range(min(chunk_count, total)):
        selected.append(all_chunks[(cursor + offset) % total])

    return ChunkPlan(
        targets=tuple(selected),
        next_cursor=(cursor + len(selected)) % total,
        total_chunks=total,
    )


def plan_full_sweep(monitored_cidrs: list[str]) -> ChunkPlan:
    targets = tuple(enumerate_all_chunks(monitored_cidrs))
    return ChunkPlan(targets=targets, next_cursor=0, total_chunks=len(targets))


def chunks_per_cycle(config: MonitorPolicyConfig) -> int:
    if config.scan_strategy == SCAN_STRATEGY_FULL:
        return len(enumerate_all_chunks(list(config.monitored_cidrs)))
    return config.chunk_count


def compute_min_interval_minutes(config: MonitorPolicyConfig) -> int:
    cycle_chunks = max(chunks_per_cycle(config), 1)
    scan_duration_seconds = cycle_chunks * SECONDS_PER_CHUNK
    min_minutes = math.ceil(scan_duration_seconds * SAFETY_MARGIN / 60)
    return max(min_minutes, MIN_INTERVAL_FLOOR_MINUTES)


def compute_full_coverage_hours(config: MonitorPolicyConfig) -> float | None:
    if config.scan_strategy == SCAN_STRATEGY_FULL:
        return float(config.discover_interval_minutes) / 60

    all_chunks = enumerate_all_chunks(list(config.monitored_cidrs))
    if not all_chunks or config.chunk_count <= 0:
        return None

    cycles = math.ceil(len(all_chunks) / config.chunk_count)
    return cycles * config.discover_interval_minutes / 60


def build_interval_info(config: MonitorPolicyConfig) -> IntervalInfo:
    return IntervalInfo(
        min_interval_minutes=compute_min_interval_minutes(config),
        full_coverage_hours=compute_full_coverage_hours(config),
    )


def validate_discover_interval(
    config: MonitorPolicyConfig,
    interval_minutes: int,
) -> None:
    if interval_minutes < 1 or interval_minutes > 10_080:
        raise ValidationError(
            "discover_interval_minutes must be between 1 and 10080 (one week)",
        )
    min_interval = compute_min_interval_minutes(config)
    if interval_minutes < min_interval:
        raise ValidationError(
            f"discover_interval_minutes must be at least {min_interval} "
            f"for the current policy",
        )


def policy_config_from_model(policy: Any) -> MonitorPolicyConfig:
    return MonitorPolicyConfig(
        monitored_cidrs=tuple(
            normalize_monitored_cidrs(policy.monitored_cidrs),
        ),
        scan_strategy=policy.scan_strategy,
        chunk_count=policy.chunk_count,
        discover_interval_minutes=policy.discover_interval_minutes,
        vuln_rescan_days=policy.vuln_rescan_days,
        vuln_scan_enabled=policy.vuln_scan_enabled,
        vuln_modules=tuple(policy.vuln_modules or ()),
        nuclei_enabled=policy.nuclei_enabled,
        chunk_cursor=policy.chunk_cursor,
    )
