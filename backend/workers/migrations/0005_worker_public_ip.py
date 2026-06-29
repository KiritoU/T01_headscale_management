from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0004_worker_shared_edge_traefik"),
    ]

    operations = [
        migrations.AddField(
            model_name="worker",
            name="public_ip",
            field=models.GenericIPAddressField(
                blank=True,
                help_text="Last public IP observed from the worker agent heartbeat.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="worker",
            name="public_ip_override",
            field=models.GenericIPAddressField(
                blank=True,
                help_text="Manual override for DNS A records when auto-detection is wrong.",
                null=True,
            ),
        ),
    ]
