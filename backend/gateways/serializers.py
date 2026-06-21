from rest_framework import serializers

from agents.models import AgentCommand
from gateways.models import Gateway
from gateways.services import get_latest_scan_command


class EnrollmentTokenCreateSerializer(serializers.Serializer):
    max_uses = serializers.IntegerField(required=False, default=1, min_value=1, max_value=100)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class GatewaySerializer(serializers.ModelSerializer):
    tenant_slug = serializers.CharField(source="tenant.slug", read_only=True)
    agent_id = serializers.UUIDField(read_only=True)
    installed_modules = serializers.SerializerMethodField()

    class Meta:
        model = Gateway
        fields = (
            "id",
            "tenant_id",
            "tenant_slug",
            "hostname",
            "status",
            "agent_id",
            "custom_tags",
            "tailscale_node_id",
            "last_heartbeat_at",
            "installed_modules",
            "created_at",
            "updated_at",
        )

    def get_installed_modules(self, gateway: Gateway) -> list[str]:
        if gateway.agent_id is None:
            return []
        return list(
            gateway.agent.modules.order_by("name").values_list("name", flat=True),
        )


class GatewayDetailSerializer(GatewaySerializer):
    last_discover_scan = serializers.SerializerMethodField()
    last_target_scan = serializers.SerializerMethodField()
    last_monitor_scan = serializers.SerializerMethodField()

    class Meta(GatewaySerializer.Meta):
        fields = GatewaySerializer.Meta.fields + (
            "last_discover_scan",
            "last_target_scan",
            "last_monitor_scan",
        )

    def get_last_discover_scan(self, gateway: Gateway) -> dict | None:
        command = get_latest_scan_command(gateway, "discover")
        if command is None:
            return None
        return GatewayCommandDetailSerializer(command).data

    def get_last_target_scan(self, gateway: Gateway) -> dict | None:
        command = get_latest_scan_command(gateway, "target")
        if command is None:
            return None
        return GatewayCommandDetailSerializer(command).data

    def get_last_monitor_scan(self, gateway: Gateway) -> dict | None:
        command = get_latest_scan_command(gateway, "monitor")
        if command is None:
            return None
        return GatewayCommandDetailSerializer(command).data


class GatewayTagsSerializer(serializers.Serializer):
    custom_tags = serializers.ListField(
        child=serializers.CharField(max_length=128),
        allow_empty=True,
    )


class GatewayCommandSerializer(serializers.Serializer):
    command = serializers.ChoiceField(
        choices=[
            "scan_network",
            "tailscale_up",
            "tailscale_status",
            "install_module",
            "vuln_scan",
        ],
    )
    payload = serializers.JSONField(required=False, default=dict)


class TailscaleUpPayloadSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    advertise_routes = serializers.ListField(
        child=serializers.CharField(max_length=64),
        min_length=1,
    )
    force_reauth = serializers.BooleanField(required=False, default=True)
    accept_dns = serializers.BooleanField(required=False, default=True)
    reset = serializers.BooleanField(required=False, default=True)


class TailscaleTenantOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.CharField()
    headscale_host = serializers.CharField()
    bootstrap_status = serializers.CharField()
    credentials_ready = serializers.BooleanField()


class TenantTailscalePreviewSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    slug = serializers.CharField()
    login_server = serializers.CharField()
    auth_key_available = serializers.BooleanField()
    auth_key_hint = serializers.CharField(allow_null=True)


class TailscaleLastScanSerializer(serializers.Serializer):
    command_id = serializers.UUIDField()
    scan_mode = serializers.ChoiceField(choices=["discover", "target"])
    acked_at = serializers.DateTimeField(allow_null=True)
    subnets = serializers.ListField(child=serializers.DictField())
    summary = serializers.DictField()


class TailscaleUpOptionDefaultsSerializer(serializers.Serializer):
    force_reauth = serializers.BooleanField()
    accept_dns = serializers.BooleanField()
    reset = serializers.BooleanField()


class TailscaleConnectContextSerializer(serializers.Serializer):
    gateway_tenant_id = serializers.UUIDField()
    tenants = TailscaleTenantOptionSerializer(many=True)
    default_tenant_id = serializers.UUIDField()
    tenant_preview = TenantTailscalePreviewSerializer()
    last_scan = TailscaleLastScanSerializer(allow_null=True)
    option_defaults = TailscaleUpOptionDefaultsSerializer()


def redact_sensitive_command_payload(payload: dict | None) -> dict:
    if not payload:
        return {}
    redacted = dict(payload)
    if "auth_key" in redacted:
        redacted["auth_key"] = "[redacted]"
    return redacted


class GatewayCommandDetailSerializer(serializers.ModelSerializer):
    payload = serializers.SerializerMethodField()

    class Meta:
        model = AgentCommand
        fields = (
            "id",
            "command",
            "payload",
            "state",
            "result",
            "acked_at",
            "created_at",
        )

    def get_payload(self, command: AgentCommand) -> dict:
        return redact_sensitive_command_payload(command.payload)


class GatewayCommandResponseSerializer(serializers.ModelSerializer):
    payload = serializers.SerializerMethodField()

    class Meta:
        model = AgentCommand
        fields = ("id", "command", "payload", "state", "created_at")

    def get_payload(self, command: AgentCommand) -> dict:
        return redact_sensitive_command_payload(command.payload)
