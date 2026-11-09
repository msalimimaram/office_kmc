from django.db import migrations, models


def mark_existing_records_legacy(apps, schema_editor):
    AssetValuation = apps.get_model("assets", "AssetValuation")
    AssetPolicyEndorsement = apps.get_model("assets", "AssetPolicyEndorsement")
    db = schema_editor.connection.alias
    AssetValuation.objects.using(db).update(status="legacy")
    AssetPolicyEndorsement.objects.using(db).update(status="legacy")


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
                    ("legacy", "سابقه قدیمی؛ فاقد تأیید در گردش جدید"),
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
                    ("legacy", "سابقه قدیمی؛ فاقد تأیید در گردش جدید"),
                ],
                default="pending_approval",
                max_length=24,
                verbose_name="وضعیت تأیید",
            ),
        ),
        migrations.RunPython(
            mark_existing_records_legacy,
            migrations.RunPython.noop,
        ),
    ]
