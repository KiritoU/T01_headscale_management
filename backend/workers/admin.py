from django.contrib import admin

from workers.models import Worker


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "docker_reachable", "last_heartbeat_at")
    list_filter = ("status", "docker_reachable")
    search_fields = ("name", "hostname")
