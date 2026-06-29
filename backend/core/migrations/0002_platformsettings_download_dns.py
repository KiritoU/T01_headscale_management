from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_platformsettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformsettings",
            name="cf_token_verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="download_host",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="platformsettings",
            name="download_target_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
    ]
