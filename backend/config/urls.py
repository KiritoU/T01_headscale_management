import os
import sys

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts.urls import admin_urlpatterns, auth_urlpatterns
from core.scripts import gateway_agent_script, worker_agent_script
from gateways.bundles import ensure_gateway_bundles, gateway_module_bundle

ensure_gateway_bundles()

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include(auth_urlpatterns)),
    # Core routes (console-settings, edge-settings, scripts) must be registered
    # before api/admin/ so /api/admin/console-settings/ is not swallowed by accounts.
    path("api/", include("core.urls")),
    path("api/admin/", include(admin_urlpatterns)),
    path("api/v1/", include("agents.urls")),
    path("api/tenants/", include("tenants.urls")),
    path("api/workers/", include("workers.urls")),
    path("api/gateways/", include("gateways.urls")),
    path("gateway-agent.sh", gateway_agent_script, name="gateway-agent-script"),
    path("worker-agent.sh", worker_agent_script, name="worker-agent-script"),
    path(
        "gateway-vuln-nse-pack.tar.gz",
        gateway_module_bundle,
        {"bundle_name": "gateway-vuln-nse-pack.tar.gz"},
        name="gateway-vuln-nse-pack",
    ),
    path(
        "gateway-iot-probes.tar.gz",
        gateway_module_bundle,
        {"bundle_name": "gateway-iot-probes.tar.gz"},
        name="gateway-iot-probes",
    ),
]

_serve_openapi = (
    settings.DEBUG
    or os.environ.get("DJANGO_TEST") == "1"
    or "pytest" in sys.modules
)

if _serve_openapi:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
