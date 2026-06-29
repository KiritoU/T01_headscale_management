from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.request import Request
from rest_framework.views import APIView

from lifecycle.deployment import login_server_url, tenant_production_mode
from lifecycle.scripts import SUPPORTED_SCRIPT_NAMES, generate_script
from tenants.models import Tenant


class TenantScriptView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, slug: str, script_name: str) -> HttpResponse:
        if script_name not in SUPPORTED_SCRIPT_NAMES:
            return HttpResponse("Not found", status=404, content_type="text/plain")
        tenant = get_object_or_404(Tenant, slug=slug)
        production = tenant_production_mode(tenant.desired_config)
        login_server = login_server_url(tenant.headscale_host, production=production)
        content = generate_script(script_name, login_server=login_server)
        return HttpResponse(content, content_type="text/plain; charset=utf-8")
