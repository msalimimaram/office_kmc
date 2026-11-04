from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("auditlog", "0001_initial"),
        ("accounts", "0003_role_assignment_foundation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_events",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="before_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="داده قبل از تغییر"),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="after_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="داده بعد از تغییر"),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="metadata",
            field=models.JSONField(blank=True, default=dict, verbose_name="اطلاعات تکمیلی"),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="user_agent",
            field=models.CharField(blank=True, max_length=512, verbose_name="مرورگر/عامل کاربر"),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="correlation_id",
            field=models.UUIDField(blank=True, db_index=True, null=True, verbose_name="شناسه همبستگی"),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="created_at",
            field=models.DateTimeField(db_index=True, default=django.utils.timezone.now, editable=False, verbose_name="زمان رخداد"),
        ),
    ]
