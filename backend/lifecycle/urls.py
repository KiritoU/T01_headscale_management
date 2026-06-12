from django.urls import path

from lifecycle.views import (
    TenantBootstrapView,
    TenantConfigView,
    TenantScriptView,
    TenantVerifyView,
)

urlpatterns = [
    path("<uuid:tenant_id>/config/", TenantConfigView.as_view(), name="tenant-config"),
    path("<uuid:tenant_id>/scripts/<str:name>/", TenantScriptView.as_view(), name="tenant-script"),
    path("<uuid:tenant_id>/verify/", TenantVerifyView.as_view(), name="tenant-verify"),
    path("<uuid:tenant_id>/bootstrap/", TenantBootstrapView.as_view(), name="tenant-bootstrap"),
]
