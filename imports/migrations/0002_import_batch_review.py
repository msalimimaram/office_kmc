from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0001_initial"),
        ("accounts", "0003_role_assignment_foundation"),
    ]

    operations = [
        migrations.AddField(
            model_name="importbatch",
            name="reviewed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reviewed_import_batches", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان تأیید"),
        ),
        migrations.AddField(
            model_name="importbatch",
            name="review_note",
            field=models.TextField(blank=True, verbose_name="یادداشت بررسی"),
        ),
        migrations.AlterField(
            model_name="importbatch",
            name="status",
            field=models.CharField(choices=[("uploaded", "بارگذاری‌شده"), ("validated", "اعتبارسنجی‌شده و در انتظار تأیید"), ("processed", "تأیید و پردازش‌شده"), ("failed", "ناموفق")], default="uploaded", max_length=16, verbose_name="وضعیت"),
        ),
    ]
