from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ScopeType
from accounts.permissions import (
    DenyViewerOnWorkersGateways,
    IsAuthenticatedHuman,
    ScopedResourceAccess,
)
from core.responses import api_envelope
from lifecycle.generator import generate_tenant_config
from lifecycle.scripts import SUPPORTED_SCRIPT_NAMES, generate_script
from lifecycle.services import (
    TenantLifecycleError,
    enqueue_bootstrap_tenant,
    enqueue_verify_tenant,
)
from tenants.models import Tenant


class TenantConfigView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.TENANT

    def get_scope_id(self, obj: Tenant):
        return obj.id

    def get(self, request: Request, tenant_id: str) -> Response:
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        self.check_object_permissions(request, tenant)
        return Response(generate_tenant_config(tenant))


class TenantScriptView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.TENANT

    def get_scope_id(self, obj: Tenant):
        return obj.id

    def get(self, request: Request, tenant_id: str, name: str) -> Response | HttpResponse:
        tenant = get_object_or_404(Tenant, pk=tenant_id)
        self.check_object_permissions(request, tenant)
        if name not in SUPPORTED_SCRIPT_NAMES:
            return Response(
                api_envelope(error=f"Unsupported script: {name}"),
                status=status.HTTP_404_NOT_FOUND,
            )

        config = generate_tenant_config(tenant)
        content = generate_script(name, login_server=config["login_server"])
        response = HttpResponse(content, content_type="text/x-shellscript; charset=utf-8")
        response["Content-Disposition"] = f'inline; filename="{name}"'
        return response


class TenantVerifyView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.TENANT

    def get_scope_id(self, obj: Tenant):
        return obj.id

    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_object_or_404(Tenant.objects.select_related("worker__agent"), pk=tenant_id)
        self.check_object_permissions(request, tenant)
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
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )


class TenantBootstrapView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticatedHuman, DenyViewerOnWorkersGateways, ScopedResourceAccess]
    scope_type = ScopeType.TENANT

    def get_scope_id(self, obj: Tenant):
        return obj.id

    def post(self, request: Request, tenant_id: str) -> Response:
        tenant = get_object_or_404(Tenant.objects.select_related("worker__agent"), pk=tenant_id)
        self.check_object_permissions(request, tenant)
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
                }
            ),
            status=status.HTTP_202_ACCEPTED,
        )
