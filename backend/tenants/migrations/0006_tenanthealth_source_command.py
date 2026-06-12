from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def _latency_ms(result: dict) -> int:
    duration_ms = result.get("duration_ms", 0)
    try:
        return max(0, min(int(duration_ms), 999_999))
    except (TypeError, ValueError):
        return 0


def _error_message(result: dict, healthy: bool) -> str:
    if healthy:
        return ""
    logs = result.get("logs")
    if isinstance(logs, str) and logs.strip():
        return logs.strip()[:500]
    return ""


def backfill_health_from_verify_commands(apps, schema_editor) -> None:
    AgentCommand = apps.get_model("agents", "AgentCommand")
    Tenant = apps.get_model("tenants", "Tenant")
    TenantHealth = apps.get_model("tenants", "TenantHealth")

    commands = AgentCommand.objects.filter(command="verify_tenant").exclude(
        state="pending",
    ).order_by("acked_at", "created_at")

    for command in commands.iterator():
        tenant_id = (command.payload or {}).get("tenant_id")
        if not tenant_id:
            continue
        if TenantHealth.objects.filter(source_command_id=command.id).exists():
            continue
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            continue

        result = dict(command.result or {})
        healthy = command.state == "acked" and result.get("exit_code") == 0
        TenantHealth.objects.create(
            tenant=tenant,
            source_command_id=command.id,
            probed_at=command.acked_at or command.created_at,
            latency_ms=_latency_ms(result),
            healthy=healthy,
            error_message=_error_message(result, healthy),
        )


def trim_health_history(apps, schema_editor) -> None:
    Tenant = apps.get_model("tenants", "Tenant")
    TenantHealth = apps.get_model("tenants", "TenantHealth")
    limit = 5

    for tenant in Tenant.objects.iterator():
        keep_ids = list(
            TenantHealth.objects.filter(tenant=tenant)
            .order_by("-probed_at")
            .values_list("id", flat=True)[:limit],
        )
        if keep_ids:
            TenantHealth.objects.filter(tenant=tenant).exclude(id__in=keep_ids).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0001_initial"),
        ("tenants", "0005_tenant_bootstrap_secrets"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenanthealth",
            name="source_command",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tenant_health_record",
                to="agents.agentcommand",
            ),
        ),
        migrations.RunPython(backfill_health_from_verify_commands, migrations.RunPython.noop),
        migrations.RunPython(trim_health_history, migrations.RunPython.noop),
    ]
