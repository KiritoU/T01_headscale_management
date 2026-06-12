from django.contrib import admin

from agents.models import Agent, AgentCommand, AgentModule


class AgentCommandInline(admin.TabularInline):
    model = AgentCommand
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at", "dispatched_at", "acked_at")
    fields = (
        "command",
        "state",
        "payload",
        "result",
        "dispatched_at",
        "acked_at",
        "created_at",
    )


class AgentModuleInline(admin.TabularInline):
    model = AgentModule
    extra = 0
    readonly_fields = ("id", "updated_at")


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_type", "token_prefix", "poll_interval_seconds", "last_seen_at")
    list_filter = ("agent_type",)
    search_fields = ("id", "token_prefix")
    readonly_fields = ("id", "token_hash", "created_at", "updated_at")
    inlines = [AgentCommandInline, AgentModuleInline]


@admin.register(AgentCommand)
class AgentCommandAdmin(admin.ModelAdmin):
    list_display = ("command", "agent", "state", "created_at", "dispatched_at", "acked_at")
    list_filter = ("state", "command")
    search_fields = ("command", "agent__id")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AgentModule)
class AgentModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "agent", "installed_at", "updated_at")
    search_fields = ("name", "agent__id")
    readonly_fields = ("id", "updated_at")
