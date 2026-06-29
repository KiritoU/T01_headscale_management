import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0007_runtime_status_deleting"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagedDnsRecord",
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
                ("fqdn", models.CharField(max_length=255, unique=True)),
                ("record_type", models.CharField(default="A", max_length=8)),
                ("zone_id", models.CharField(max_length=64)),
                ("cf_record_id", models.CharField(max_length=64)),
                ("target_ip", models.GenericIPAddressField()),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("tenant_headscale", "Tenant headscale"),
                            ("tenant_headplane", "Tenant headplane"),
                            ("console_download", "Console download"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="managed_dns_records",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "ordering": ["fqdn"],
            },
        ),
    ]
