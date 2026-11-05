from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0002_task_event_history"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="internaltask",
            options={
                "ordering": ["status", "due_at", "-created_at"],
                "verbose_name": "وظیفه",
                "verbose_name_plural": "وظایف داخلی",
            },
        ),
    ]
