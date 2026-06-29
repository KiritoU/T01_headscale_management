from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_runtime_status_deleting"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
