from django.db import migrations, models
import django.db.models.deletion


def backfill_contract_lifecycle(apps, schema_editor):
    Contract = apps.get_model("insurance", "Contract")
    ContractRevision = apps.get_model("insurance", "ContractRevision")

    for contract in Contract.objects.all().iterator():
        contract.status = "active" if contract.is_active else "legacy_inactive"
        contract.save(update_fields=["status"])

    ContractRevision.objects.all().update(status="legacy")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("insurance", "0002_contractrevision"),
    ]

    operations = [
        migrations.AddField(
            model_name="contract",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "پیش‌نویس"),
                    ("pending_approval", "در انتظار تأیید"),
                    ("approved", "تأییدشده؛ در انتظار تاریخ اثر"),
                    ("active", "فعال"),
                    ("expired", "منقضی"),
                    ("terminated", "فسخ‌شده"),
                    ("rejected", "ردشده"),
                    ("legacy_inactive", "غیرفعال قدیمی"),
                ],
                default="draft",
                max_length=24,
                verbose_name="وضعیت چرخه عمر",
            ),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_approval", "در انتظار تأیید"),
                    ("approved", "تأییدشده"),
                    ("rejected", "ردشده"),
                    ("terminated", "فسخ تأییدشده"),
                    ("legacy", "نسخه قدیمی؛ فاقد گردش تأیید جدید"),
                ],
                default="pending_approval",
                max_length=24,
                verbose_name="وضعیت نسخه",
            ),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="snapshot",
            field=models.JSONField(blank=True, default=dict, verbose_name="تصویر کامل شرایط نسخه"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="effective_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ اثر"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="approved_contract_revisions",
                to="accounts.user",
            ),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان تأیید"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="applied_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان اعمال نسخه"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="is_termination",
            field=models.BooleanField(default=False, verbose_name="درخواست فسخ"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="termination_reason",
            field=models.TextField(blank=True, verbose_name="علت فسخ"),
        ),
        migrations.AddField(
            model_name="contractrevision",
            name="notice_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ اعلام فسخ"),
        ),
        migrations.RunPython(backfill_contract_lifecycle, migrations.RunPython.noop),
    ]
