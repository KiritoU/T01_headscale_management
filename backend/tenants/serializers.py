from rest_framework import serializers

from tenants.detail import get_bootstrap_info, recent_health_checks
from tenants.legacy import import_legacy_tenant
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant, TenantHealth
from tenants.validators import validate_desired_config
from workers.models import Worker


class TenantHealthSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantHealth
        fields = (
            "id",
            "probed_at",
            "latency_ms",
            "healthy",
            "error_message",
        )
        read_only_fields = fields


class TenantSerializer(serializers.ModelSerializer):
    worker = serializers.PrimaryKeyRelatedField(read_only=True)
    worker_name = serializers.CharField(source="worker.name", read_only=True, allow_null=True)

    class Meta:
        model = Tenant
        fields = (
            "id",
            "slug",
            "headscale_host",
            "headplane_host",
            "db_name",
            "worker",
            "worker_name",
            "bootstrap_status",
            "bootstrap_output_ref",
            "runtime_status",
            "desired_config",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TenantDetailSerializer(TenantSerializer):
    health_checks = serializers.SerializerMethodField()
    bootstrap_info = serializers.SerializerMethodField()

    class Meta(TenantSerializer.Meta):
        fields = TenantSerializer.Meta.fields + ("health_checks", "bootstrap_info")

    def get_health_checks(self, tenant: Tenant) -> list[dict]:
        checks = recent_health_checks(tenant)
        return TenantHealthSerializer(checks, many=True).data

    def get_bootstrap_info(self, tenant: Tenant) -> dict | None:
        return get_bootstrap_info(tenant)


class TenantWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "slug",
            "headscale_host",
            "headplane_host",
            "db_name",
            "worker",
            "bootstrap_status",
            "desired_config",
        )

    def validate_desired_config(self, value):
        return validate_desired_config(value)

    def validate_bootstrap_status(self, value):
        if value not in BootstrapStatus.values:
            raise serializers.ValidationError(f"Invalid bootstrap_status: {value}")
        return value


class ImportLegacyTenantSerializer(serializers.Serializer):
    suffix = serializers.CharField(max_length=32)
    number = serializers.IntegerField(min_value=1)
    base_domain = serializers.CharField(max_length=255)
    worker_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate_worker_id(self, value):
        if value is not None and not Worker.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Worker not found.")
        return value

    def create(self, validated_data: dict) -> Tenant:
        return import_legacy_tenant(**validated_data)
