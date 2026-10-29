from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("requests_portal", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="InternalTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=250, verbose_name="عنوان")),
                ("description", models.TextField(verbose_name="شرح")),
                ("priority", models.CharField(choices=[("low","کم"),("normal","عادی"),("high","زیاد"),("urgent","فوری")], default="normal", max_length=12, verbose_name="اولویت")),
                ("status", models.CharField(choices=[("open","باز"),("in_progress","در حال انجام"),("waiting","در انتظار"),("done","انجام‌شده"),("cancelled","لغوشده")], default="open", max_length=16, verbose_name="وضعیت")),
                ("due_at", models.DateTimeField(blank=True, null=True, verbose_name="مهلت انجام")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_tasks", to=settings.AUTH_USER_MODEL)),
                ("related_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="requests_portal.servicerequest")),
                ("assignees", models.ManyToManyField(related_name="internal_tasks", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["status","due_at","-created_at"]},
        ),
    ]
