from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin, IsAuthenticatedHuman
from core.edge_settings import get_platform_settings
from core.public_url import get_public_base_url
from core.responses import api_envelope
from core.serializers import (
    PlatformConsoleSettingsSerializer,
    PlatformConsoleSettingsUpdateSerializer,
    PlatformEdgeSettingsSerializer,
    PlatformEdgeSettingsUpdateSerializer,
)
from dns.services import (
    DnsConfigurationError,
    download_dns_status,
    ensure_download_dns,
    resolve_platform_cf_token_resolution,
)
from integrations.cloudflare import verify_token


class PublicConfigView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        from core.console_download import get_console_download_host

        return Response(
            api_envelope(
                data={
                    "public_base_url": get_public_base_url(request),
                    "download_host": get_console_download_host(),
                    "version": settings.APP_VERSION,
                }
            )
        )


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(
            api_envelope(
                data={
                    "status": "ok",
                    "service": "headscale-management",
                    "version": settings.APP_VERSION,
                }
            )
        )


class PlatformEdgeSettingsView(APIView):
    permission_classes = [IsAuthenticatedHuman, IsAdmin]

    def get(self, request: Request) -> Response:
        settings_row = get_platform_settings()
        serializer = PlatformEdgeSettingsSerializer(settings_row)
        return Response(api_envelope(data=serializer.data))

    def patch(self, request: Request) -> Response:
        settings_row = get_platform_settings()
        serializer = PlatformEdgeSettingsUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.update_settings(settings_row)
        return Response(
            api_envelope(data=PlatformEdgeSettingsSerializer(updated).data),
            status=status.HTTP_200_OK,
        )


class PlatformConsoleSettingsView(APIView):
    permission_classes = [IsAuthenticatedHuman, IsAdmin]

    def get(self, request: Request) -> Response:
        settings_row = get_platform_settings()
        serializer = PlatformConsoleSettingsSerializer(settings_row)
        return Response(api_envelope(data=serializer.data))

    def patch(self, request: Request) -> Response:
        settings_row = get_platform_settings()
        serializer = PlatformConsoleSettingsUpdateSerializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.update_settings(settings_row)
        return Response(
            api_envelope(data=PlatformConsoleSettingsSerializer(updated).data),
            status=status.HTTP_200_OK,
        )


class PlatformVerifyCloudflareView(APIView):
    permission_classes = [IsAuthenticatedHuman, IsAdmin]

    def post(self, request: Request) -> Response:
        resolution = resolve_platform_cf_token_resolution()
        token = resolution.token
        if not token:
            return Response(
                api_envelope(
                    data={
                        "valid": False,
                        "status": "missing",
                        "message": "Token not set",
                        "token_source": resolution.source,
                    },
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_row = verify_token(token)
        if status_row.valid:
            settings_row = get_platform_settings()
            settings_row.cf_token_verified_at = timezone.now()
            settings_row.save(update_fields=["cf_token_verified_at", "updated_at"])
        return Response(
            api_envelope(
                data={
                    "valid": status_row.valid,
                    "status": status_row.status,
                    "message": status_row.message,
                    "token_source": resolution.source,
                    "cf_token_verified_at": (
                        get_platform_settings().cf_token_verified_at.isoformat()
                        if status_row.valid and get_platform_settings().cf_token_verified_at
                        else None
                    ),
                },
            ),
            status=status.HTTP_200_OK if status_row.valid else status.HTTP_400_BAD_REQUEST,
        )


class PlatformSyncDownloadDnsView(APIView):
    permission_classes = [IsAuthenticatedHuman, IsAdmin]

    def post(self, request: Request) -> Response:
        settings_row = get_platform_settings()
        try:
            record = ensure_download_dns(settings_row)
        except DnsConfigurationError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_row = download_dns_status()
        return Response(
            api_envelope(
                data={
                    "fqdn": record.fqdn,
                    "target_ip": record.target_ip,
                    "cf_record_id": record.cf_record_id,
                    "synced": bool(status_row and status_row.synced),
                },
            ),
        )
