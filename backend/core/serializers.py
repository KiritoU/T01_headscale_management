from rest_framework import serializers

from core.models import PlatformSettings
from dns.services import resolve_platform_cf_token_resolution


class PlatformEdgeSettingsSerializer(serializers.ModelSerializer):
    cf_dns_api_token_configured = serializers.SerializerMethodField()
    cf_dns_api_token_source = serializers.SerializerMethodField()

    class Meta:
        model = PlatformSettings
        fields = (
            "acme_email",
            "cf_dns_api_token_configured",
            "cf_dns_api_token_source",
            "updated_at",
        )
        read_only_fields = ("cf_dns_api_token_configured", "cf_dns_api_token_source", "updated_at")

    def get_cf_dns_api_token_configured(self, obj: PlatformSettings) -> bool:
        return bool(resolve_platform_cf_token_resolution().token)

    def get_cf_dns_api_token_source(self, obj: PlatformSettings) -> str:
        return resolve_platform_cf_token_resolution().source


class PlatformEdgeSettingsUpdateSerializer(serializers.Serializer):
    acme_email = serializers.EmailField(required=False, allow_blank=True)
    cf_dns_api_token = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
        trim_whitespace=True,
    )

    def update_settings(self, instance: PlatformSettings) -> PlatformSettings:
        acme_email = self.validated_data.get("acme_email")
        if acme_email is not None:
            instance.acme_email = acme_email.strip()

        token = self.validated_data.get("cf_dns_api_token")
        if token is not None:
            cleaned = token.strip()
            if cleaned:
                instance.cf_dns_api_token = cleaned
                instance.cf_token_verified_at = None
            else:
                instance.cf_dns_api_token = ""
                instance.cf_token_verified_at = None

        instance.save()
        return instance


class PlatformConsoleSettingsSerializer(serializers.ModelSerializer):
    cf_dns_api_token_configured = serializers.SerializerMethodField()
    cf_dns_api_token_source = serializers.SerializerMethodField()
    download_dns_synced = serializers.SerializerMethodField()
    download_dns_record_id = serializers.SerializerMethodField()

    class Meta:
        model = PlatformSettings
        fields = (
            "acme_email",
            "cf_dns_api_token_configured",
            "cf_dns_api_token_source",
            "cf_token_verified_at",
            "download_host",
            "download_target_ip",
            "download_dns_synced",
            "download_dns_record_id",
            "updated_at",
        )
        read_only_fields = (
            "cf_dns_api_token_configured",
            "cf_dns_api_token_source",
            "cf_token_verified_at",
            "download_dns_synced",
            "download_dns_record_id",
            "updated_at",
        )

    def get_cf_dns_api_token_configured(self, obj: PlatformSettings) -> bool:
        return bool(resolve_platform_cf_token_resolution().token)

    def get_cf_dns_api_token_source(self, obj: PlatformSettings) -> str:
        return resolve_platform_cf_token_resolution().source

    def get_download_dns_synced(self, obj: PlatformSettings) -> bool:
        from dns.services import download_dns_status

        status = download_dns_status()
        return bool(status and status.synced)

    def get_download_dns_record_id(self, obj: PlatformSettings) -> str | None:
        from dns.services import download_dns_status

        status = download_dns_status()
        return status.cf_record_id if status else None


class PlatformConsoleSettingsUpdateSerializer(serializers.Serializer):
    acme_email = serializers.EmailField(required=False, allow_blank=True)
    cf_dns_api_token = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=512,
        trim_whitespace=True,
    )
    download_host = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        trim_whitespace=True,
    )
    download_target_ip = serializers.IPAddressField(required=False, allow_null=True)

    def update_settings(self, instance: PlatformSettings) -> PlatformSettings:
        acme_email = self.validated_data.get("acme_email")
        if acme_email is not None:
            instance.acme_email = acme_email.strip()

        token = self.validated_data.get("cf_dns_api_token")
        if token is not None:
            cleaned = token.strip()
            if cleaned:
                instance.cf_dns_api_token = cleaned
                instance.cf_token_verified_at = None
            else:
                instance.cf_dns_api_token = ""
                instance.cf_token_verified_at = None

        download_host = self.validated_data.get("download_host")
        if download_host is not None:
            instance.download_host = download_host.strip().lower()

        if "download_target_ip" in self.validated_data:
            instance.download_target_ip = self.validated_data.get("download_target_ip")

        instance.save()
        return instance
