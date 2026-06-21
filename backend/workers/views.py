from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.mixins import ScopedQuerysetMixin
from accounts.models import ScopeType
from accounts.permissions import (
    DenyViewerOnWorkersGateways,
    IsAuthenticatedHuman,
    ScopedResourceAccess,
)
from agents.liveness import mark_stale_workers_and_gateways_offline
from agents.serializers import AgentCommandResponseSerializer
from core.public_url import build_agent_install_curl
from core.responses import api_envelope
from workers.bundle import build_agent_daemon_tarball
from workers.models import Worker
from workers.serializers import (
    WorkerCommandSerializer,
    WorkerEnrollmentTokenCreateSerializer,
    WorkerSerializer,
)
from workers.services import (
    create_worker_enrollment_token,
    delete_worker,
    disconnect_worker,
    enqueue_worker_command,
)


class WorkerViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    scope_type = ScopeType.WORKER
    queryset = Worker.objects.select_related("agent").prefetch_related("agent__modules")
    serializer_class = WorkerSerializer
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        mark_stale_workers_and_gateways_offline()
        return self.filter_by_scope(super().get_queryset())

    def get_scope_id(self, obj: Worker):
        return obj.id

    def destroy(self, request: Request, *args, **kwargs) -> Response:
        worker = self.get_object()
        try:
            delete_worker(worker)
        except ValueError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkerDisconnectView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.WORKER

    def get_scope_id(self, obj: Worker):
        return obj.id

    def post(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(Worker, id=worker_id)
        self.check_object_permissions(request, worker)
        try:
            disconnect_worker(worker)
        except ValueError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )

        worker.refresh_from_db()
        serializer = WorkerSerializer(worker)
        return Response(api_envelope(data=serializer.data))


class WorkerCommandView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.WORKER

    def get_scope_id(self, obj: Worker):
        return obj.id

    def post(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(
            Worker.objects.select_related("agent"),
            id=worker_id,
        )
        self.check_object_permissions(request, worker)
        serializer = WorkerCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            command = enqueue_worker_command(
                worker,
                data["command"],
                data.get("payload", {}),
            )
        except ValueError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_data = AgentCommandResponseSerializer(command).data
        return Response(api_envelope(data=response_data), status=status.HTTP_201_CREATED)


class WorkerEnrollmentTokenCreateView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways]
    scope_type = ScopeType.WORKER

    def post(self, request: Request) -> Response:
        serializer = WorkerEnrollmentTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            creds = create_worker_enrollment_token(
                data["name"],
                expires_in_minutes=data.get("expires_in_minutes", 60),
            )
        except ValueError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            api_envelope(
                data={
                    "token": creds.raw_token,
                    "worker_id": creds.worker_id,
                    "expires_at": creds.expires_at,
                    "name": data["name"],
                    "install_command": build_agent_install_curl(
                        request,
                        script_name="worker-agent.sh",
                        token=creds.raw_token,
                    ),
                },
            ),
            status=status.HTTP_201_CREATED,
        )


class WorkerAgentDaemonBundleView(APIView):
    """Tarball of agent_daemon for worker install scripts (no auth — public bootstrap)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request: Request) -> HttpResponse:
        payload = build_agent_daemon_tarball()
        response = HttpResponse(payload, content_type="application/gzip")
        response["Content-Disposition"] = 'attachment; filename="agent-daemon.tar.gz"'
        return response
