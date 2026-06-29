from django.urls import path

from gateways.views import (
    GatewayCommandDetailView,
    GatewayCommandView,
    GatewayDetailView,
    GatewayListView,
    GatewayMetricsView,
    GatewayRoutesView,
    GatewayTagsView,
    TailscaleConnectContextView,
)
from gateways.monitoring_views import (
    GatewayMonitoringAlertsView,
    GatewayMonitoringEnsureModulesView,
    GatewayMonitoringFindingsView,
    GatewayMonitoringHostsView,
    GatewayMonitoringScanView,
    GatewayMonitoringVulnRescanView,
    GatewayMonitoringView,
)

urlpatterns = [
    path("", GatewayListView.as_view(), name="gateway-list"),
    path("<uuid:gateway_id>/", GatewayDetailView.as_view(), name="gateway-detail"),
    path("<uuid:gateway_id>/metrics/", GatewayMetricsView.as_view(), name="gateway-metrics"),
    path("<uuid:gateway_id>/tags/", GatewayTagsView.as_view(), name="gateway-tags"),
    path("<uuid:gateway_id>/routes/", GatewayRoutesView.as_view(), name="gateway-routes"),
    path(
        "<uuid:gateway_id>/monitoring/",
        GatewayMonitoringView.as_view(),
        name="gateway-monitoring",
    ),
    path(
        "<uuid:gateway_id>/monitoring/hosts/",
        GatewayMonitoringHostsView.as_view(),
        name="gateway-monitoring-hosts",
    ),
    path(
        "<uuid:gateway_id>/monitoring/alerts/",
        GatewayMonitoringAlertsView.as_view(),
        name="gateway-monitoring-alerts",
    ),
    path(
        "<uuid:gateway_id>/monitoring/findings/",
        GatewayMonitoringFindingsView.as_view(),
        name="gateway-monitoring-findings",
    ),
    path(
        "<uuid:gateway_id>/monitoring/modules/ensure/",
        GatewayMonitoringEnsureModulesView.as_view(),
        name="gateway-monitoring-ensure-modules",
    ),
    path(
        "<uuid:gateway_id>/monitoring/scan/",
        GatewayMonitoringScanView.as_view(),
        name="gateway-monitoring-scan",
    ),
    path(
        "<uuid:gateway_id>/monitoring/vuln-rescan/",
        GatewayMonitoringVulnRescanView.as_view(),
        name="gateway-monitoring-vuln-rescan",
    ),
    path(
        "<uuid:gateway_id>/commands/<uuid:cmd_id>/",
        GatewayCommandDetailView.as_view(),
        name="gateway-command-detail",
    ),
    path("<uuid:gateway_id>/commands/", GatewayCommandView.as_view(), name="gateway-commands"),
    path(
        "<uuid:gateway_id>/tailscale-up/context/",
        TailscaleConnectContextView.as_view(),
        name="gateway-tailscale-up-context",
    ),
]
