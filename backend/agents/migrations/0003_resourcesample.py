import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0002_agent_tenant_inventory"),
    ]

    operations = [
        migrations.CreateModel(
            name="ResourceSample",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("sampled_at", models.DateTimeField(db_index=True)),
                ("cpu_percent", models.FloatField(blank=True, null=True)),
                ("mem_percent", models.FloatField(blank=True, null=True)),
                ("disk_percent", models.FloatField(blank=True, null=True)),
                ("mem_total_bytes", models.BigIntegerField(blank=True, null=True)),
                ("mem_used_bytes", models.BigIntegerField(blank=True, null=True)),
                ("disk_total_bytes", models.BigIntegerField(blank=True, null=True)),
                ("disk_used_bytes", models.BigIntegerField(blank=True, null=True)),
                ("net_rx_bytes_per_sec", models.BigIntegerField(blank=True, null=True)),
                ("net_tx_bytes_per_sec", models.BigIntegerField(blank=True, null=True)),
                ("load_avg_1m", models.FloatField(blank=True, null=True)),
                ("cpu_count", models.PositiveIntegerField(blank=True, null=True)),
                ("uptime_seconds", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resource_samples",
                        to="agents.agent",
                    ),
                ),
            ],
            options={
                "ordering": ["-sampled_at"],
                "indexes": [
                    models.Index(fields=["agent", "sampled_at"], name="agents_reso_agent_i_6f0f0d_idx"),
                ],
            },
        ),
    ]
