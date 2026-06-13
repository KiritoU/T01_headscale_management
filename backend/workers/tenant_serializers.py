from rest_framework import serializers

from lifecycle.identifiers import validate_suffix
from tenants.detail import get_bootstrap_info, recent_health_checks
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant
from tenants.serializers import TenantHealthSerializer, redact_bootstrap_info_for_user


class WorkerTenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "slug",
            "headscale_host",
            "headplane_host",
            "db_name",
            "bootstrap_status",
            "runtime_status",
            "bootstrap_output_ref",
            "desired_config",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class WorkerTenantBulkCreateSerializer(serializers.Serializer):
    suffix = serializers.CharField(max_length=32)
    start_number = serializers.IntegerField(min_value=1)
    count = serializers.IntegerField(min_value=1, max_value=100)
    base_domain = serializers.CharField(max_length=255)
    production = serializers.BooleanField(required=False, default=False)

    def validate_suffix(self, value: str) -> str:
        try:
            return validate_suffix(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class WorkerTenantSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    bootstrap_status = serializers.DictField(child=serializers.IntegerField())
    runtime_status = serializers.DictField(child=serializers.IntegerField())


class WorkerTenantDetailSerializer(WorkerTenantSerializer):
    health_checks = serializers.SerializerMethodField()
    bootstrap_info = serializers.SerializerMethodField()

    class Meta(WorkerTenantSerializer.Meta):
        fields = WorkerTenantSerializer.Meta.fields + ("health_checks", "bootstrap_info")

    def get_health_checks(self, tenant: Tenant) -> list[dict]:
        checks = recent_health_checks(tenant)
        return TenantHealthSerializer(checks, many=True).data

    def get_bootstrap_info(self, tenant: Tenant) -> dict | None:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        return redact_bootstrap_info_for_user(get_bootstrap_info(tenant), user, tenant=tenant)


class WorkerTenantCommandPollSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    command = serializers.CharField()
    state = serializers.CharField()
    payload = serializers.DictField()
    result = serializers.DictField()
    created_at = serializers.DateTimeField()
    acked_at = serializers.DateTimeField(allow_null=True)
    runtime_status = serializers.ChoiceField(choices=RuntimeStatus.choices, required=False)
    bootstrap_status = serializers.ChoiceField(choices=BootstrapStatus.choices, required=False)
