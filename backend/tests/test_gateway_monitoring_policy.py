import pytest
from django.core.exceptions import ValidationError

from gateways.monitoring_policy import (
    DEFAULT_MONITORED_CIDRS,
    SCAN_STRATEGY_FULL,
    MonitorPolicyConfig,
    compute_full_coverage_hours,
    compute_min_interval_minutes,
    enumerate_all_chunks,
    normalize_monitored_cidrs,
    plan_rotating_chunks,
    validate_discover_interval,
    validate_monitored_cidrs,
)


class TestNormalizeMonitoredCidrs:
    def test_default_when_empty(self):
        assert normalize_monitored_cidrs(None) == list(DEFAULT_MONITORED_CIDRS)
        assert normalize_monitored_cidrs([]) == list(DEFAULT_MONITORED_CIDRS)


class TestValidateMonitoredCidrs:
    def test_accepts_default_16(self):
        result = validate_monitored_cidrs(["192.168.0.0/16"])
        assert result == ["192.168.0.0/16"]

    def test_rejects_10_slash_8(self):
        with pytest.raises(ValidationError, match="not allowed"):
            validate_monitored_cidrs(["10.0.0.0/8"])

    def test_rejects_too_many_cidrs(self):
        cidrs = [f"192.168.{i}.0/24" for i in range(9)]
        with pytest.raises(ValidationError, match="At most 8"):
            validate_monitored_cidrs(cidrs)

    def test_admin_override_allows_10_slash_8(self):
        result = validate_monitored_cidrs(["10.0.0.0/8"], allow_large_cidrs=True)
        assert result == ["10.0.0.0/8"]


class TestRotatingChunks:
    def test_default_16_yields_256_chunks(self):
        chunks = enumerate_all_chunks(["192.168.0.0/16"])
        assert len(chunks) == 256
        assert chunks[0] == "192.168.0.0/24"
        assert chunks[-1] == "192.168.255.0/24"

    def test_plan_rotates_four_chunks(self):
        plan = plan_rotating_chunks(
            ["192.168.0.0/16"],
            chunk_count=4,
            chunk_cursor=0,
        )
        assert plan.targets == (
            "192.168.0.0/24",
            "192.168.1.0/24",
            "192.168.2.0/24",
            "192.168.3.0/24",
        )
        assert plan.next_cursor == 4
        assert plan.total_chunks == 256

    def test_plan_wraps_cursor(self):
        plan = plan_rotating_chunks(
            ["192.168.0.0/16"],
            chunk_count=4,
            chunk_cursor=254,
        )
        assert len(plan.targets) == 4
        assert plan.next_cursor == 2


class TestIntervalCalculation:
    def _default_config(self, **kwargs) -> MonitorPolicyConfig:
        base = {
            "monitored_cidrs": ("192.168.0.0/16",),
            "scan_strategy": "rotating_chunks",
            "chunk_count": 4,
            "discover_interval_minutes": 60,
        }
        base.update(kwargs)
        return MonitorPolicyConfig(**base)

    def test_min_interval_default_is_10_minutes(self):
        config = self._default_config()
        assert compute_min_interval_minutes(config) == 10

    def test_full_coverage_at_60_min(self):
        config = self._default_config()
        hours = compute_full_coverage_hours(config)
        assert hours == pytest.approx(64.0)

    def test_rejects_interval_below_min(self):
        config = self._default_config(scan_strategy=SCAN_STRATEGY_FULL)
        min_interval = compute_min_interval_minutes(config)
        with pytest.raises(ValidationError, match=f"at least {min_interval}"):
            validate_discover_interval(config, min_interval - 1)
