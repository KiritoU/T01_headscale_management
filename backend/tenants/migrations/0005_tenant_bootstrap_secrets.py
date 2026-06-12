from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_tenant_runtime_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="bootstrap_secrets",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
