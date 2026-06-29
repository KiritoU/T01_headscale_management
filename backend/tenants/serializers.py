from rest_framework import serializers

from core.console_download import get_console_download_host
from tenants.detail import get_bootstrap_info, recent_health_checks
from tenants.legacy import import_legacy_tenant
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant, TenantHealth
from tenants.validators import validate_desired_config
from workers.models import Worker

_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "auth_key_gateway",
        "auth_key_workspace",
        "auth_key",
    }
)


def user_can_view_tenant_secrets(user, tenant: Tenant | None) -> bool:
    """Admins and users with scoped tenant access may read bootstrap credentials."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_admin", False):
        return True
    if tenant is None or not hasattr(user, "role"):
        return False

    from accounts.models import ScopeType
    from accounts.scoping import effective_access

    return effective_access(user, scope_type=ScopeType.TENANT, scope_id=tenant.id) is not None


def redact_secrets_from_mapping(
    data: dict | None,
    user,
    *,
    tenant: Tenant | None = None,
) -> dict | None:
    if data is None:
        return None
    if user_can_view_tenant_secrets(user, tenant):
        return data

    sanitized = dict(data)
    for key in _SECRET_FIELDS:
        sanitized.pop(key, None)

    for nested_key in ("bootstrap_info", "bootstrap"):
        nested = sanitized.get(nested_key)
        if isinstance(nested, dict):
            sanitized[nested_key] = redact_secrets_from_mapping(nested, user, tenant=tenant)

    return sanitized


def redact_bootstrap_info_for_user(
    bootstrap_info: dict | None,
    user,
    *,
    tenant: Tenant | None = None,
) -> dict | None:
    return redact_secrets_from_mapping(bootstrap_info, user, tenant=tenant)


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
    connect_download_host = serializers.SerializerMethodField()

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
            "description",
            "connect_download_host",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at", "connect_download_host")

    def get_connect_download_host(self, tenant: Tenant) -> str:
        return get_console_download_host()


class TenantDetailSerializer(TenantSerializer):
    health_checks = serializers.SerializerMethodField()
    bootstrap_info = serializers.SerializerMethodField()

    class Meta(TenantSerializer.Meta):
        fields = TenantSerializer.Meta.fields + ("health_checks", "bootstrap_info")

    def get_health_checks(self, tenant: Tenant) -> list[dict]:
        checks = recent_health_checks(tenant)
        return TenantHealthSerializer(checks, many=True).data

    def get_bootstrap_info(self, tenant: Tenant) -> dict | None:
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        return redact_bootstrap_info_for_user(get_bootstrap_info(tenant), user, tenant=tenant)


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
            "description",
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
