from __future__ import annotations

import shutil
from typing import Any

import pytest

from agent_daemon.system_metrics import SystemMetricsCollector


PROC_STAT_1 = """cpu  0 0 0 1000 0 0 0 0 0 0
cpu0 0 0 0 250 0 0 0 0 0 0
"""

PROC_STAT_2 = """cpu  0 0 250 1250 0 0 0 0 0 0
cpu0 0 0 62 312 0 0 0 0 0 0
"""

PROC_MEMINFO = """MemTotal:       16384000 kB
MemAvailable:    8192000 kB
"""

PROC_NET_DEV_1 = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000      10    0    0    0     0          0         0     1000      10    0    0    0     0       0          0
  eth0: 1000000   1000  0    0    0     0          0         0   500000    500    0    0    0     0       0          0
"""

PROC_NET_DEV_2 = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 2000      20    0    0    0     0          0         0     2000      20    0    0    0     0       0          0
  eth0: 1015000   1100  0    0    0     0          0         0   520000    550    0    0    0     0       0          0
"""

PROC_UPTIME = "12345.67 98765.43\n"


class FakeClock:
    def __init__(self, start: float = 1000.0, step: float = 15.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        current = self._value
        self._value += self._step
        return current


def _build_collector(
    *,
    stat_sequence: list[str] | None = None,
    net_sequence: list[str] | None = None,
    clock: FakeClock | None = None,
) -> SystemMetricsCollector:
    stat_reads = list(stat_sequence or [PROC_STAT_1, PROC_STAT_2])
    net_reads = list(net_sequence or [PROC_NET_DEV_1, PROC_NET_DEV_2])

    def read_text(path: str) -> str:
        if path == "/proc/stat":
            if not stat_reads:
                return PROC_STAT_2
            return stat_reads.pop(0)
        if path == "/proc/meminfo":
            return PROC_MEMINFO
        if path == "/proc/net/dev":
            if not net_reads:
                return PROC_NET_DEV_2
            return net_reads.pop(0)
        if path == "/proc/uptime":
            return PROC_UPTIME
        raise FileNotFoundError(path)

    def disk_usage(_path: str) -> tuple[int, int, int]:
        return (100 * 1024**3, 40 * 1024**3, 60 * 1024**3)

    return SystemMetricsCollector(
        read_text=read_text,
        disk_usage=disk_usage,
        monotonic=clock or FakeClock(),
    )


class TestSystemMetricsCollector:
    def test_first_sample_has_null_delta_metrics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("agent_daemon.system_metrics.os.getloadavg", lambda: (1.25, 0.5, 0.25))
        monkeypatch.setattr("agent_daemon.system_metrics.os.cpu_count", lambda: 4)

        collector = _build_collector(stat_sequence=[PROC_STAT_1], net_sequence=[PROC_NET_DEV_1])
        sample = collector.sample()

        assert sample["cpu_percent"] is None
        assert sample["net_rx_bytes_per_sec"] is None
        assert sample["net_tx_bytes_per_sec"] is None
        assert sample["mem_total_bytes"] == 16384000 * 1024
        assert sample["mem_used_bytes"] == 8192000 * 1024
        assert sample["mem_percent"] == 50.0
        assert sample["disk_total_bytes"] == 100 * 1024**3
        assert sample["disk_used_bytes"] == 40 * 1024**3
        assert sample["disk_percent"] == 40.0
        assert sample["load_avg_1m"] == 1.25
        assert sample["cpu_count"] == 4
        assert sample["uptime_seconds"] == pytest.approx(12345.67)

    def test_second_sample_computes_cpu_and_network_rates(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("agent_daemon.system_metrics.os.getloadavg", lambda: (2.0, 1.0, 0.5))
        monkeypatch.setattr("agent_daemon.system_metrics.os.cpu_count", lambda: 8)

        collector = _build_collector()
        first = collector.sample()
        second = collector.sample()

        assert first["cpu_percent"] is None
        assert second["cpu_percent"] == 50.0
        assert second["net_rx_bytes_per_sec"] == 1000
        assert second["net_tx_bytes_per_sec"] == pytest.approx(1333, rel=0.01)

    def test_collector_handles_missing_proc_files(self) -> None:
        def read_text(_path: str) -> str:
            raise OSError("missing")

        collector = SystemMetricsCollector(
            read_text=read_text,
            disk_usage=lambda _path: (_ for _ in ()).throw(OSError("missing")),
        )
        sample = collector.sample()

        assert sample["cpu_percent"] is None
        assert sample["mem_total_bytes"] is None
        assert sample["disk_total_bytes"] is None
        assert sample["net_rx_bytes_per_sec"] is None
