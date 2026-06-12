import os
import sys

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core.scripts import gateway_agent_script, worker_agent_script

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
    path("api/v1/", include("agents.urls")),
    path("api/tenants/", include("tenants.urls")),
    path("api/workers/", include("workers.urls")),
    path("api/gateways/", include("gateways.urls")),
    path("gateway-agent.sh", gateway_agent_script, name="gateway-agent-script"),
    path("worker-agent.sh", worker_agent_script, name="worker-agent-script"),
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
