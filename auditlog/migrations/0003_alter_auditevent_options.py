from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("auditlog", "0002_immutable_structured_events"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="auditevent",
            options={
                "ordering": ["-created_at", "-pk"],
                "verbose_name": "رویداد ممیزی",
                "verbose_name_plural": "رویدادهای ممیزی",
            },
        ),
    ]
