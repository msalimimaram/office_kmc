from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
        ("accounts", "0003_role_assignment_foundation"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("created", "ایجاد"), ("assigned", "تخصیص"), ("status", "تغییر وضعیت"), ("comment", "یادداشت"), ("due_changed", "تغییر مهلت")], max_length=20)),
                ("from_value", models.CharField(blank=True, max_length=80)),
                ("to_value", models.CharField(blank=True, max_length=80)),
                ("note", models.TextField(blank=True)),
                ("occurred_at", models.DateTimeField(default=timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="tasks.internaltask")),
            ],
            options={"verbose_name": "رویداد وظیفه", "verbose_name_plural": "تاریخچه وظایف", "ordering": ("occurred_at", "pk")},
        ),
    ]
