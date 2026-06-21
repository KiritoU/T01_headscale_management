from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.scoping import effective_access
from accounts.models import AccessLevel, ScopeType
from core.responses import api_envelope
from gateways.models import DiscoveredHost, Gateway, MonitorAlert, VulnFinding
from gateways.module_service import (
    discovery_required_modules,
    ensure_modules_installed,
    required_modules,
)
from gateways.monitoring_serializers import (
    DiscoveredHostSerializer,
    GatewayMonitorPolicySerializer,
    MonitorAlertSerializer,
    VulnFindingSerializer,
)
from gateways.monitoring_pagination import (
    filter_alerts_queryset,
    filter_findings_queryset,
    filter_hosts_queryset,
    paginate_queryset,
    parse_pagination_params,
)
from gateways.monitoring_service import (
    MonitorScanTriggerError,
    build_policy_response,
    get_or_create_monitor_policy,
    trigger_immediate_monitor_scan,
    trigger_vuln_rescan,
)
from gateways.views import GatewayScopedAPIView


class GatewayMonitoringView(GatewayScopedAPIView):

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        policy = get_or_create_monitor_policy(gateway)
        return Response(api_envelope(data=build_policy_response(policy)))

    def patch(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        policy = get_or_create_monitor_policy(gateway)
        allow_large = getattr(request.user, "is_admin", False)
        serializer = GatewayMonitorPolicySerializer(
            data=request.data,
            context={"policy": policy, "allow_large_cidrs": allow_large},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        updates = dict(data)
        if updates:
            from gateways.models import GatewayMonitorPolicy

            GatewayMonitorPolicy.objects.filter(pk=policy.pk).update(**updates)
            policy.refresh_from_db()

        return Response(api_envelope(data=build_policy_response(policy)))


class GatewayMonitoringHostsView(GatewayScopedAPIView):

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        page, limit = parse_pagination_params(request)
        queryset = filter_hosts_queryset(
            DiscoveredHost.objects.filter(gateway=gateway).order_by("ip"),
            request,
        )
        hosts, meta = paginate_queryset(queryset, page=page, limit=limit)
        serializer = DiscoveredHostSerializer(hosts, many=True)
        return Response(api_envelope(data=serializer.data, meta=meta))


class GatewayMonitoringAlertsView(GatewayScopedAPIView):

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        page, limit = parse_pagination_params(request)
        queryset = filter_alerts_queryset(
            MonitorAlert.objects.filter(gateway=gateway).order_by("-created_at"),
            request,
        )
        alerts, meta = paginate_queryset(queryset, page=page, limit=limit)
        serializer = MonitorAlertSerializer(alerts, many=True)
        return Response(api_envelope(data=serializer.data, meta=meta))


class GatewayMonitoringFindingsView(GatewayScopedAPIView):

    def get(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        page, limit = parse_pagination_params(request)
        queryset = filter_findings_queryset(
            VulnFinding.objects.filter(discovered_host__gateway=gateway)
            .select_related("discovered_host")
            .order_by("-found_at"),
            request,
        )
        findings, meta = paginate_queryset(queryset, page=page, limit=limit)
        serializer = VulnFindingSerializer(findings, many=True)
        return Response(api_envelope(data=serializer.data, meta=meta))


class GatewayMonitoringEnsureModulesView(GatewayScopedAPIView):

    def post(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        if not getattr(request.user, "is_admin", False):
            access = effective_access(request.user, ScopeType.GATEWAY, gateway.id)
            if access != AccessLevel.EDIT:
                return Response(
                    api_envelope(error="Edit access required to install modules"),
                    status=status.HTTP_403_FORBIDDEN,
                )

        policy = get_or_create_monitor_policy(gateway)
        modules = list(discovery_required_modules())
        if policy.vuln_scan_enabled:
            for name in required_modules(policy, include_optional=True):
                if name not in modules:
                    modules.append(name)
        ready = ensure_modules_installed(gateway, modules)
        policy.refresh_from_db()
        gateway.refresh_from_db()
        return Response(
            api_envelope(
                data={
                    "ready": ready,
                    "policy": build_policy_response(policy),
                },
            ),
        )


class GatewayMonitoringScanView(GatewayScopedAPIView):

    def post(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        if not getattr(request.user, "is_admin", False):
            access = effective_access(request.user, ScopeType.GATEWAY, gateway.id)
            if access != AccessLevel.EDIT:
                return Response(
                    api_envelope(error="Edit access required to trigger a scan"),
                    status=status.HTTP_403_FORBIDDEN,
                )

        try:
            command = trigger_immediate_monitor_scan(gateway)
        except MonitorScanTriggerError as exc:
            return Response(
                api_envelope(error=exc.message),
                status=exc.status_code,
            )

        targets = list((command.payload or {}).get("targets") or [])
        return Response(
            api_envelope(
                data={
                    "command_id": str(command.id),
                    "targets": targets,
                    "state": command.state,
                },
            ),
            status=status.HTTP_201_CREATED,
        )


class GatewayMonitoringVulnRescanView(GatewayScopedAPIView):

    def post(self, request: Request, gateway_id: str) -> Response:
        gateway = get_object_or_404(Gateway, id=gateway_id)
        self.check_object_permissions(request, gateway)
        if not getattr(request.user, "is_admin", False):
            access = effective_access(request.user, ScopeType.GATEWAY, gateway.id)
            if access != AccessLevel.EDIT:
                return Response(
                    api_envelope(error="Edit access required to trigger vuln rescan"),
                    status=status.HTTP_403_FORBIDDEN,
                )

        ip = str(request.data.get("ip", "")).strip() or None
        try:
            result = trigger_vuln_rescan(gateway, ip=ip)
        except MonitorScanTriggerError as exc:
            return Response(
                api_envelope(error=exc.message),
                status=exc.status_code,
            )

        return Response(
            api_envelope(data=result),
            status=status.HTTP_201_CREATED,
        )
