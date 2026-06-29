from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies: list[tuple[str, str]] = []

    operations = [
        migrations.CreateModel(
            name="PlatformSettings",
            fields=[
                (
                    "singleton_id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("acme_email", models.EmailField(blank=True, default="", max_length=254)),
                (
                    "cf_dns_api_token",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "platform settings",
                "verbose_name_plural": "platform settings",
            },
        ),
    ]
