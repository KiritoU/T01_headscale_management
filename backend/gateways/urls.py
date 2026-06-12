from django.urls import path

from gateways.views import (
    GatewayCommandDetailView,
    GatewayCommandView,
    GatewayDetailView,
    GatewayListView,
    GatewayRoutesView,
    GatewayTagsView,
    TailscaleConnectContextView,
)

urlpatterns = [
    path("", GatewayListView.as_view(), name="gateway-list"),
    path("<uuid:gateway_id>/", GatewayDetailView.as_view(), name="gateway-detail"),
    path("<uuid:gateway_id>/tags/", GatewayTagsView.as_view(), name="gateway-tags"),
    path("<uuid:gateway_id>/routes/", GatewayRoutesView.as_view(), name="gateway-routes"),
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
