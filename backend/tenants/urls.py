from django.urls import include, path
from rest_framework.routers import DefaultRouter

from gateways.views import EnrollmentTokenCreateView
from tenants.views import TenantViewSet

router = DefaultRouter()
router.register("", TenantViewSet, basename="tenant")

urlpatterns = [
    path(
        "<uuid:tenant_id>/gateways/enrollment-tokens/",
        EnrollmentTokenCreateView.as_view(),
        name="gateway-enrollment-token-create",
    ),
    path("", include("lifecycle.urls")),
    path("", include(router.urls)),
]
