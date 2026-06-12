from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.liveness import mark_stale_workers_and_gateways_offline
from agents.models import AgentCommand
from core.permissions import DebugOrTestAllowAny
from core.responses import api_envelope
from gateways.models import Gateway
from gateways.serializers import (
    EnrollmentTokenCreateSerializer,
    GatewayCommandDetailSerializer,
    GatewayCommandResponseSerializer,
    GatewayCommandSerializer,
    GatewayDetailSerializer,
    GatewaySerializer,
    GatewayTagsSerializer,
    TailscaleConnectContextSerializer,
    TailscaleUpPayloadSerializer,
)
from gateways.tailscale import build_tailscale_connect_context
from gateways.services import (
    create_enrollment_token,
    delete_gateway,
    enqueue_gateway_command,
    sync_gateway_routes,
)
from tenants.models import Tenant


class EnrollmentTokenCreateView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_object_or_404(Tenant, id=tenant_id)
        serializer = EnrollmentTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        creds = create_enrollment_token(
            tenant,
            max_uses=data.get("max_uses", 1),
            expires_at=data.get("expires_at"),
        )

        return Response(
            api_envelope(
                data={
                    "token_id": creds.token_id,
                    "token": creds.raw_token,
                    "prefix": creds.prefix,
                    "max_uses": creds.max_uses,
                    "expires_at": creds.expires_at,
                },
            ),
            status=status.HTTP_201_CREATED,
        )


class GatewayListView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request) -> Response:
        mark_stale_workers_and_gateways_offline()
        queryset = Gateway.objects.select_related("tenant", "agent").prefetch_related(
            "agent__modules",
        )
        tenant_id = request.query_params.get("tenant_id")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)

        serializer = GatewaySerializer(queryset, many=True)
        return Response(api_envelope(data=serializer.data))


class GatewayDetailView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, gateway_id: str) -> Response:
        mark_stale_workers_and_gateways_offline()
        gateway = get_object_or_404(
            Gateway.objects.select_related("tenant", "agent").prefetch_related(
                "agent__modules",
            ),
            id=gateway_id,
        )
        serializer = GatewayDetailSerializer(gateway)
        return Response(api_envelope(data=serializer.data))

    def delete(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        delete_gateway(gateway)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GatewayRoutesView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        return Response(api_envelope(data=sync_gateway_routes(gateway)))


class GatewayTagsView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def patch(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        serializer = GatewayTagsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tags = serializer.validated_data["custom_tags"]
        Gateway.objects.filter(pk=gateway.pk).update(custom_tags=tags)
        gateway.refresh_from_db()

        return Response(api_envelope(data=GatewaySerializer(gateway).data))


class TailscaleConnectContextView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(
            Gateway.objects.select_related("tenant"),
            id=gateway_id,
        )
        tenant_id = request.query_params.get("tenant_id")
        try:
            context = build_tailscale_connect_context(gateway, tenant_id=tenant_id)
        except Tenant.DoesNotExist:
            return Response(
                api_envelope(error="Tenant not found"),
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TailscaleConnectContextSerializer(data=context)
        serializer.is_valid(raise_exception=True)
        return Response(api_envelope(data=serializer.validated_data))


class GatewayCommandView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(
            Gateway.objects.select_related("agent"),
            id=gateway_id,
        )
        serializer = GatewayCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payload = dict(data.get("payload") or {})
        if data["command"] == "tailscale_up" and payload.get("tenant_id") is not None:
            ts_serializer = TailscaleUpPayloadSerializer(data=payload)
            ts_serializer.is_valid(raise_exception=True)
            payload = dict(ts_serializer.validated_data)
            payload["tenant_id"] = str(payload["tenant_id"])

        try:
            command = enqueue_gateway_command(
                gateway,
                data["command"],
                payload,
            )
        except ValueError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_data = GatewayCommandResponseSerializer(command).data
        return Response(api_envelope(data=response_data), status=status.HTTP_201_CREATED)


class GatewayCommandDetailView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, gateway_id: str, cmd_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        if gateway.agent_id is None:
            return Response(
                api_envelope(error="Gateway has no enrolled agent"),
                status=status.HTTP_404_NOT_FOUND,
            )

        command = get_object_or_404(
            AgentCommand,
            id=cmd_id,
            agent_id=gateway.agent_id,
        )
        serializer = GatewayCommandDetailSerializer(command)
        return Response(api_envelope(data=serializer.data))
