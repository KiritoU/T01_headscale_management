from django.urls import path

from core.script_views import TenantScriptView
from core.views import (
    HealthView,
    PlatformConsoleSettingsView,
    PlatformEdgeSettingsView,
    PlatformSyncDownloadDnsView,
    PlatformVerifyCloudflareView,
    PublicConfigView,
)

urlpatterns = [
    path("config/", PublicConfigView.as_view(), name="public-config"),
    path("health/", HealthView.as_view(), name="health"),
    path(
        "admin/edge-settings/",
        PlatformEdgeSettingsView.as_view(),
        name="platform-edge-settings",
    ),
    path(
        "admin/console-settings/",
        PlatformConsoleSettingsView.as_view(),
        name="platform-console-settings",
    ),
    path(
        "admin/console-settings/verify-cloudflare/",
        PlatformVerifyCloudflareView.as_view(),
        name="platform-verify-cloudflare",
    ),
    path(
        "admin/console-settings/sync-download-dns/",
        PlatformSyncDownloadDnsView.as_view(),
        name="platform-sync-download-dns",
    ),
    path(
        "scripts/<slug:slug>/<path:script_name>",
        TenantScriptView.as_view(),
        name="tenant-script",
    ),
]
