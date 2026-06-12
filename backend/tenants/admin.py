from django.contrib import admin

from tenants.models import Tenant, TenantHealth


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("slug", "bootstrap_status", "worker", "headscale_host")
    list_filter = ("bootstrap_status",)
    search_fields = ("slug", "headscale_host", "headplane_host")


@admin.register(TenantHealth)
class TenantHealthAdmin(admin.ModelAdmin):
    list_display = ("tenant", "probed_at", "latency_ms", "healthy")
    list_filter = ("healthy",)
