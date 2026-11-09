from django.db import migrations, models
from django.db.models import F


def mark_legacy_valuations_approved(apps, schema_editor):
    AssetValuation = apps.get_model("assets", "AssetValuation")
    db = schema_editor.connection.alias
    AssetValuation.objects.using(db).filter(
        method="legacy_snapshot"
    ).update(
        status="approved",
        approved_by_id=F("created_by_id"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0002_personal_ownership_and_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetvaluation",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_approval", "در انتظار تأیید"),
                    ("approved", "تأییدشده"),
                    ("rejected", "ردشده"),
                ],
                default="pending_approval",
                max_length=24,
                verbose_name="وضعیت تأیید",
            ),
        ),
        migrations.AlterField(
            model_name="assetpolicyperiod",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "پیش‌نویس"),
                    ("pending_approval", "در انتظار تأیید"),
                    ("approved", "تأییدشده؛ در انتظار شروع پوشش"),
                    ("active", "فعال"),
                    ("rejected", "ردشده"),
                    ("expired", "منقضی"),
                    ("terminated", "فسخ‌شده"),
                    ("superseded", "جایگزین‌شده"),
                ],
                default="draft",
                max_length=16,
                verbose_name="وضعیت",
            ),
        ),
        migrations.AddField(
            model_name="assetpolicyendorsement",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_approval", "در انتظار تأیید"),
                    ("approved", "تأییدشده"),
                    ("rejected", "ردشده"),
                ],
                default="pending_approval",
                max_length=24,
                verbose_name="وضعیت تأیید",
            ),
        ),
        migrations.RunPython(
            mark_legacy_valuations_approved,
            migrations.RunPython.noop,
        ),
    ]
