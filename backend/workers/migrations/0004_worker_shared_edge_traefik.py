from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workers", "0003_workerenrollmenttoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="worker",
            name="shared_edge_traefik",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When true, tenant stacks omit a local Traefik instance and "
                    "use the control plane edge proxy for TLS."
                ),
            ),
        ),
    ]
