"""Host resource metrics for agent heartbeats (stdlib only — no psutil)."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


ReadTextFn = Callable[[str], str]
DiskUsageFn = Callable[[str], tuple[int, int, int]]
MonotonicFn = Callable[[], float]


@dataclass(frozen=True)
class _CpuCounters:
    total_jiffies: int
    idle_jiffies: int


@dataclass(frozen=True)
class _NetCounters:
    rx_bytes: int
    tx_bytes: int


def _default_read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _parse_cpu_line(line: str) -> _CpuCounters | None:
    if not line.startswith("cpu "):
        return None
    parts = line.split()
    if len(parts) < 5:
        return None
    values = [int(value) for value in parts[1:]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return _CpuCounters(total_jiffies=sum(values), idle_jiffies=idle)


def _parse_meminfo(text: str) -> tuple[int, int] | None:
    mem_total: int | None = None
    mem_available: int | None = None
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) * 1024
        elif line.startswith("MemAvailable:"):
            mem_available = int(line.split()[1]) * 1024
    if mem_total is None or mem_available is None:
        return None
    mem_used = max(mem_total - mem_available, 0)
    return mem_total, mem_used


def _parse_net_dev(text: str) -> _NetCounters:
    rx_bytes = 0
    tx_bytes = 0
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        interface, stats = line.split(":", maxsplit=1)
        name = interface.strip()
        if not name or name == "lo":
            continue
        columns = stats.split()
        if len(columns) < 9:
            continue
        rx_bytes += int(columns[0])
        tx_bytes += int(columns[8])
    return _NetCounters(rx_bytes=rx_bytes, tx_bytes=tx_bytes)


def _parse_uptime_seconds(text: str) -> float | None:
    parts = text.split()
    if not parts:
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def _percent(used: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((used / total) * 100.0, 2)


def _rate_per_sec(delta: int, elapsed_seconds: float) -> int | None:
    if elapsed_seconds <= 0:
        return None
    return max(int(delta / elapsed_seconds), 0)


class SystemMetricsCollector:
    """Stateful collector; delta metrics are None on the first sample."""

    def __init__(
        self,
        *,
        read_text: ReadTextFn | None = None,
        disk_usage: DiskUsageFn | None = None,
        monotonic: MonotonicFn | None = None,
        disk_path: str = "/",
    ) -> None:
        self._read_text = read_text or _default_read_text
        self._disk_usage = disk_usage or shutil.disk_usage
        self._monotonic = monotonic or time.monotonic
        self._disk_path = disk_path
        self._prev_cpu: _CpuCounters | None = None
        self._prev_net: _NetCounters | None = None
        self._prev_monotonic: float | None = None

    def sample(self) -> dict[str, Any]:
        now = self._monotonic()
        elapsed = (now - self._prev_monotonic) if self._prev_monotonic is not None else None

        cpu_percent = self._sample_cpu_percent(elapsed)
        net_rx, net_tx = self._sample_net_rates(elapsed)
        mem = self._sample_memory()
        disk = self._sample_disk()
        load_avg_1m = self._sample_load_avg()
        uptime_seconds = self._sample_uptime_seconds()
        cpu_count = os.cpu_count()

        self._prev_monotonic = now

        payload: dict[str, Any] = {
            "cpu_percent": cpu_percent,
            "mem_total_bytes": mem[0] if mem else None,
            "mem_used_bytes": mem[1] if mem else None,
            "mem_percent": _percent(mem[1], mem[0]) if mem else None,
            "disk_total_bytes": disk[0] if disk else None,
            "disk_used_bytes": disk[1] if disk else None,
            "disk_percent": _percent(disk[1], disk[0]) if disk else None,
            "net_rx_bytes_per_sec": net_rx,
            "net_tx_bytes_per_sec": net_tx,
            "load_avg_1m": load_avg_1m,
            "cpu_count": cpu_count,
            "uptime_seconds": uptime_seconds,
        }
        return payload

    def _sample_cpu_percent(self, elapsed: float | None) -> float | None:
        try:
            stat_text = self._read_text("/proc/stat")
        except OSError:
            return None

        counters = _parse_cpu_line(stat_text.splitlines()[0])
        if counters is None:
            return None

        cpu_percent: float | None = None
        if self._prev_cpu is not None and elapsed is not None and elapsed > 0:
            total_delta = counters.total_jiffies - self._prev_cpu.total_jiffies
            idle_delta = counters.idle_jiffies - self._prev_cpu.idle_jiffies
            if total_delta > 0:
                usage = 1.0 - (idle_delta / total_delta)
                cpu_percent = round(max(min(usage * 100.0, 100.0), 0.0), 2)

        self._prev_cpu = counters
        return cpu_percent

    def _sample_net_rates(self, elapsed: float | None) -> tuple[int | None, int | None]:
        try:
            net_text = self._read_text("/proc/net/dev")
        except OSError:
            return None, None

        counters = _parse_net_dev(net_text)
        rx_rate: int | None = None
        tx_rate: int | None = None
        if self._prev_net is not None and elapsed is not None:
            rx_rate = _rate_per_sec(counters.rx_bytes - self._prev_net.rx_bytes, elapsed)
            tx_rate = _rate_per_sec(counters.tx_bytes - self._prev_net.tx_bytes, elapsed)

        self._prev_net = counters
        return rx_rate, tx_rate

    def _sample_memory(self) -> tuple[int, int] | None:
        try:
            meminfo = self._read_text("/proc/meminfo")
        except OSError:
            return None
        return _parse_meminfo(meminfo)

    def _sample_disk(self) -> tuple[int, int] | None:
        try:
            usage = self._disk_usage(self._disk_path)
        except OSError:
            return None
        if isinstance(usage, tuple):
            return usage[0], usage[1]
        return usage.total, usage.used

    def _sample_load_avg(self) -> float | None:
        try:
            load_avg = os.getloadavg()
        except (AttributeError, OSError):
            return None
        return round(load_avg[0], 2)

    def _sample_uptime_seconds(self) -> float | None:
        try:
            uptime_text = self._read_text("/proc/uptime")
        except OSError:
            return None
        return _parse_uptime_seconds(uptime_text)
