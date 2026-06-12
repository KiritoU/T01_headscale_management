from django.contrib import admin

from gateways.models import EnrollmentToken, Gateway


@admin.register(EnrollmentToken)
class EnrollmentTokenAdmin(admin.ModelAdmin):
    list_display = ("prefix", "tenant", "uses", "max_uses", "revoked", "expires_at")
    list_filter = ("revoked",)
    search_fields = ("prefix", "tenant__slug")


@admin.register(Gateway)
class GatewayAdmin(admin.ModelAdmin):
    list_display = ("hostname", "tenant", "status", "last_heartbeat_at")
    list_filter = ("status",)
    search_fields = ("hostname", "tenant__slug")
