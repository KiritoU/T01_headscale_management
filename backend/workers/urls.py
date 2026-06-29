from django.urls import include, path
from rest_framework.routers import DefaultRouter

from workers.tenant_views import (
    WorkerTenantBootstrapView,
    WorkerTenantBulkCreateView,
    WorkerTenantBulkProvisionView,
    WorkerTenantCommandPollView,
    WorkerTenantDetailView,
    WorkerTenantListView,
    WorkerTenantProvisionView,
    WorkerTenantStartView,
    WorkerTenantStopView,
    WorkerTenantSummaryView,
    WorkerTenantVerifyView,
)
from workers.views import (
    WorkerAgentDaemonBundleView,
    WorkerCommandView,
    WorkerDisconnectView,
    WorkerEnrollmentTokenCreateView,
    WorkerMetricsView,
    WorkerViewSet,
)

router = DefaultRouter()
router.register("", WorkerViewSet, basename="worker")

urlpatterns = [
    path(
        "agent-daemon-bundle.tar.gz",
        WorkerAgentDaemonBundleView.as_view(),
        name="worker-agent-daemon-bundle",
    ),
    path(
        "enrollment-tokens/",
        WorkerEnrollmentTokenCreateView.as_view(),
        name="worker-enrollment-token-create",
    ),
    path(
        "<uuid:worker_id>/disconnect/",
        WorkerDisconnectView.as_view(),
        name="worker-disconnect",
    ),
    path(
        "<uuid:worker_id>/commands/",
        WorkerCommandView.as_view(),
        name="worker-commands",
    ),
    path(
        "<uuid:worker_id>/metrics/",
        WorkerMetricsView.as_view(),
        name="worker-metrics",
    ),
    path(
        "<uuid:worker_id>/tenants/summary/",
        WorkerTenantSummaryView.as_view(),
        name="worker-tenant-summary",
    ),
    path(
        "<uuid:worker_id>/tenants/bulk-create/",
        WorkerTenantBulkCreateView.as_view(),
        name="worker-tenant-bulk-create",
    ),
    path(
        "<uuid:worker_id>/tenants/bulk-provision/",
        WorkerTenantBulkProvisionView.as_view(),
        name="worker-tenant-bulk-provision",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/commands/<uuid:cmd_id>/",
        WorkerTenantCommandPollView.as_view(),
        name="worker-tenant-command-poll",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/provision/",
        WorkerTenantProvisionView.as_view(),
        name="worker-tenant-provision",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/start/",
        WorkerTenantStartView.as_view(),
        name="worker-tenant-start",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/stop/",
        WorkerTenantStopView.as_view(),
        name="worker-tenant-stop",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/verify/",
        WorkerTenantVerifyView.as_view(),
        name="worker-tenant-verify",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/bootstrap/",
        WorkerTenantBootstrapView.as_view(),
        name="worker-tenant-bootstrap",
    ),
    path(
        "<uuid:worker_id>/tenants/<uuid:tenant_id>/",
        WorkerTenantDetailView.as_view(),
        name="worker-tenant-detail",
    ),
    path(
        "<uuid:worker_id>/tenants/",
        WorkerTenantListView.as_view(),
        name="worker-tenant-list",
    ),
    path("", include(router.urls)),
]
