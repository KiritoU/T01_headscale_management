from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gateways", "0007_monitoring_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="discoveredhost",
            name="open_ports",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
