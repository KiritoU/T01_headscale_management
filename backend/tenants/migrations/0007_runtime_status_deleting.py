from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0006_tenanthealth_source_command"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="runtime_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("provisioning", "Provisioning"),
                    ("running", "Running"),
                    ("stopped", "Stopped"),
                    ("failed", "Failed"),
                    ("deleting", "Deleting"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
    ]
