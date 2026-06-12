from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.models import AgentCommand
from core.permissions import DebugOrTestAllowAny
from core.responses import api_envelope
from lifecycle.services import TenantLifecycleError, enqueue_bootstrap_tenant, enqueue_verify_tenant
from tenants.models import Tenant
from workers.models import Worker
from workers.tenant_serializers import (
    WorkerTenantBulkCreateSerializer,
    WorkerTenantCommandPollSerializer,
    WorkerTenantDetailSerializer,
    WorkerTenantSerializer,
    WorkerTenantSummarySerializer,
)
from workers.tenant_services import (
    WorkerTenantError,
    bulk_create_tenants,
    bulk_provision_pending_tenants,
    enqueue_provision_tenant,
    enqueue_start_tenant,
    enqueue_stop_tenant,
    get_tenant_summary,
    remove_tenant,
    sync_tenant_from_acked_command,
)


def _get_worker_tenant(worker_id: str, tenant_id: str) -> tuple[Worker, Tenant]:
    worker = get_object_or_404(Worker.objects.select_related("agent"), id=worker_id)
    tenant = get_object_or_404(
        Tenant.objects.select_related("worker__agent"),
        id=tenant_id,
        worker_id=worker.id,
    )
    return worker, tenant


class WorkerTenantSummaryView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(Worker, id=worker_id)
        summary = get_tenant_summary(worker)
        serializer = WorkerTenantSummarySerializer(
            {
                "total": summary.total,
                "bootstrap_status": summary.bootstrap_status,
                "runtime_status": summary.runtime_status,
            }
        )
        return Response(api_envelope(data=serializer.data))


class WorkerTenantListView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(Worker, id=worker_id)
        tenants = Tenant.objects.filter(worker=worker).order_by("slug")
        serializer = WorkerTenantSerializer(tenants, many=True)
        return Response(api_envelope(data=serializer.data))


class WorkerTenantBulkCreateView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(Worker, id=worker_id)
        serializer = WorkerTenantBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            tenants = bulk_create_tenants(
                worker,
                suffix=data["suffix"],
                start_number=data["start_number"],
                count=data["count"],
                base_domain=data["base_domain"],
                production=data.get("production", False),
            )
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        response_serializer = WorkerTenantSerializer(tenants, many=True)
        return Response(api_envelope(data=response_serializer.data), status=status.HTTP_201_CREATED)


class WorkerTenantBulkProvisionView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str) -> Response:
        worker = get_object_or_404(Worker.objects.select_related("agent"), id=worker_id)
        try:
            commands = bulk_provision_pending_tenants(worker)
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            api_envelope(
                data=[
                    {
                        "command_id": cmd.id,
                        "command": cmd.command,
                        "state": cmd.state,
                        "skipped": cmd.skipped,
                    }
                    for cmd in commands
                ]
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantProvisionView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        try:
            command = enqueue_provision_tenant(tenant)
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        tenant.refresh_from_db()
        return Response(
            api_envelope(
                data={
                    "command_id": command.id,
                    "command": command.command,
                    "state": command.state,
                    "runtime_status": tenant.runtime_status,
                    "skipped": command.skipped,
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantStartView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        try:
            command = enqueue_start_tenant(tenant)
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            api_envelope(
                data={
                    "command_id": command.id,
                    "command": command.command,
                    "state": command.state,
                    "skipped": command.skipped,
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantStopView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        try:
            command = enqueue_stop_tenant(tenant)
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            api_envelope(
                data={
                    "command_id": command.id,
                    "command": command.command,
                    "state": command.state,
                    "skipped": command.skipped,
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantVerifyView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        try:
            command = enqueue_verify_tenant(tenant)
        except TenantLifecycleError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            api_envelope(
                data={
                    "command_id": command.id,
                    "command": command.command,
                    "state": command.state,
                    "skipped": command.skipped,
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantBootstrapView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def post(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        try:
            command = enqueue_bootstrap_tenant(tenant)
        except TenantLifecycleError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        tenant.refresh_from_db()
        return Response(
            api_envelope(
                data={
                    "command_id": command.id,
                    "command": command.command,
                    "state": command.state,
                    "bootstrap_output_ref": tenant.bootstrap_output_ref,
                    "bootstrap_status": tenant.bootstrap_status,
                    "skipped": command.skipped,
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class WorkerTenantDetailView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        _worker, tenant = _get_worker_tenant(worker_id, tenant_id)
        tenant = (
            Tenant.objects.select_related("worker")
            .prefetch_related("health_checks")
            .get(pk=tenant.id)
        )
        serializer = WorkerTenantDetailSerializer(tenant)
        return Response(api_envelope(data=serializer.data))

    def delete(self, request: Request, worker_id: str, tenant_id: str) -> Response:
        worker = get_object_or_404(Worker.objects.select_related("agent"), id=worker_id)
        tenant = get_object_or_404(Tenant, id=tenant_id, worker_id=worker.id)
        try:
            remove_tenant(worker, tenant)
        except WorkerTenantError as exc:
            return Response(api_envelope(error=str(exc)), status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkerTenantCommandPollView(APIView):
    permission_classes = [DebugOrTestAllowAny]

    def get(self, request: Request, worker_id: str, tenant_id: str, cmd_id: str) -> Response:
        worker = get_object_or_404(Worker.objects.select_related("agent"), id=worker_id)
        tenant = get_object_or_404(Tenant, id=tenant_id, worker_id=worker.id)
        if worker.agent_id is None:
            return Response(
                api_envelope(error="Worker has no registered agent."),
                status=status.HTTP_400_BAD_REQUEST,
            )

        command = get_object_or_404(
            AgentCommand,
            id=cmd_id,
            agent_id=worker.agent_id,
            payload__tenant_id=str(tenant.id),
        )
        sync_tenant_from_acked_command(command)
        tenant.refresh_from_db()

        data = {
            "id": command.id,
            "command": command.command,
            "state": command.state,
            "payload": command.payload,
            "result": command.result,
            "created_at": command.created_at,
            "acked_at": command.acked_at,
            "runtime_status": tenant.runtime_status,
            "bootstrap_status": tenant.bootstrap_status,
        }
        serializer = WorkerTenantCommandPollSerializer(data)
        return Response(api_envelope(data=serializer.data))
