from __future__ import annotations

from rest_framework import serializers

from gateways.models import DiscoveredHost, GatewayMonitorPolicy, MonitorAlert, VulnFinding
from gateways.monitoring_policy import (
    SCAN_STRATEGY_FULL,
    SCAN_STRATEGY_ROTATING,
    policy_config_from_model,
    validate_discover_interval,
    validate_monitored_cidrs,
)


class GatewayMonitorPolicySerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    monitored_cidrs = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
    )
    scan_strategy = serializers.ChoiceField(
        choices=[SCAN_STRATEGY_ROTATING, SCAN_STRATEGY_FULL],
        required=False,
    )
    chunk_count = serializers.IntegerField(required=False, min_value=1, max_value=16)
    discover_interval_minutes = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=10_080,
    )
    vuln_rescan_days = serializers.IntegerField(required=False, min_value=1, max_value=90)
    vuln_scan_enabled = serializers.BooleanField(required=False)
    vuln_modules = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
    )
    nuclei_enabled = serializers.BooleanField(required=False)
    vuln_parallel_workers = serializers.IntegerField(required=False, min_value=1, max_value=16)

    def validate_monitored_cidrs(self, value: list[str]) -> list[str]:
        allow_large = self.context.get("allow_large_cidrs", False)
        return validate_monitored_cidrs(value, allow_large_cidrs=allow_large)

    def validate(self, attrs: dict) -> dict:
        policy: GatewayMonitorPolicy | None = self.context.get("policy")
        if policy is None:
            return attrs

        merged = {
            "monitored_cidrs": attrs.get("monitored_cidrs", policy.monitored_cidrs),
            "scan_strategy": attrs.get("scan_strategy", policy.scan_strategy),
            "chunk_count": attrs.get("chunk_count", policy.chunk_count),
            "discover_interval_minutes": attrs.get(
                "discover_interval_minutes",
                policy.discover_interval_minutes,
            ),
            "vuln_rescan_days": attrs.get("vuln_rescan_days", policy.vuln_rescan_days),
            "vuln_scan_enabled": attrs.get("vuln_scan_enabled", policy.vuln_scan_enabled),
            "vuln_modules": attrs.get("vuln_modules", policy.vuln_modules),
            "nuclei_enabled": attrs.get("nuclei_enabled", policy.nuclei_enabled),
            "chunk_cursor": policy.chunk_cursor,
        }
        temp = GatewayMonitorPolicy(gateway=policy.gateway, **merged)
        config = policy_config_from_model(temp)
        validate_discover_interval(config, merged["discover_interval_minutes"])
        return attrs


class DiscoveredHostSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscoveredHost
        fields = (
            "id",
            "ip",
            "hostname",
            "mac",
            "first_seen_at",
            "last_seen_at",
            "is_new",
            "vuln_scan_pending",
            "last_vuln_scan_at",
            "open_ports",
        )


class MonitorAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = MonitorAlert
        fields = (
            "id",
            "alert_type",
            "host_ip",
            "message",
            "created_at",
            "acknowledged_at",
        )


class VulnFindingSerializer(serializers.ModelSerializer):
    host_ip = serializers.CharField(source="discovered_host.ip", read_only=True)

    class Meta:
        model = VulnFinding
        fields = (
            "id",
            "host_ip",
            "source",
            "severity",
            "title",
            "finding_id",
            "details",
            "found_at",
        )
