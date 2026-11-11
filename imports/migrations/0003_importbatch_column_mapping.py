from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0002_import_batch_review"),
    ]

    operations = [
        migrations.AddField(
            model_name="importbatch",
            name="column_mapping",
            field=models.JSONField(blank=True, default=dict, verbose_name="نگاشت ستون‌های اکسل"),
        ),
    ]
