import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0005_person_change_request"),
        ("insurance", "0005_one_unapplied_contract_change"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkDelegation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("workflow_code", models.CharField(db_index=True, max_length=64, verbose_name="کد گردش‌کار")),
                ("item_type", models.CharField(blank=True, help_text="خالی یعنی تمام زیرنوع‌های این گردش‌کار؛ برای person_change مانند iban یا mobile", max_length=40, verbose_name="زیرنوع کار")),
                ("delegate_role", models.CharField(choices=[("insurance_specialist", "کارشناس اداره بیمه"), ("subsidiary_rep", "نماینده شرکت"), ("insurer_representative", "نماینده بیمه‌گر")], max_length=32, verbose_name="نقش پایه گیرنده")),
                ("line_code", models.CharField(blank=True, max_length=32, verbose_name="رشته بیمه‌ای")),
                ("reason", models.TextField(max_length=2000, verbose_name="دلیل و محدوده اختیار")),
                ("status", models.CharField(choices=[("active", "فعال"), ("suspended", "معلق"), ("revoked", "لغوشده"), ("expired", "منقضی")], default="active", max_length=16, verbose_name="وضعیت")),
                ("valid_from", models.DateField(default=django.utils.timezone.localdate, verbose_name="شروع اعتبار")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="پایان اعتبار")),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="زمان لغو")),
                ("revocation_reason", models.CharField(blank=True, max_length=1000, verbose_name="دلیل لغو/تعلیق")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="work_delegations", to="organizations.company", verbose_name="شرکت محدودکننده")),
                ("delegate_to", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="received_work_delegations", to=settings.AUTH_USER_MODEL, verbose_name="گیرنده تفویض")),
                ("granted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued_work_delegations", to=settings.AUTH_USER_MODEL, verbose_name="تفویض‌کننده")),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="work_delegations", to="insurance.insurer", verbose_name="بیمه‌گر محدودکننده")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="revoked_work_delegations", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "تفویض اختیار کاری",
                "verbose_name_plural": "تفویض‌های اختیار",
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddIndex(
            model_name="workdelegation",
            index=models.Index(fields=["workflow_code", "status", "valid_from", "valid_until"], name="delegation_lookup"),
        ),
        migrations.AddIndex(
            model_name="workdelegation",
            index=models.Index(fields=["delegate_to", "status", "valid_until"], name="delegation_inbox"),
        ),
        migrations.CreateModel(
            name="DelegationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("created", "ایجاد تفویض"), ("case_routed", "ارجاع پرونده"), ("case_returned", "بازگشت پرونده"), ("suspended", "تعلیق"), ("resumed", "فعال‌سازی مجدد"), ("revoked", "لغو"), ("expired", "انقضا")], max_length=24)),
                ("summary", models.CharField(max_length=1000)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("delegation", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="delegations.workdelegation")),
            ],
            options={
                "verbose_name": "رویداد تفویض اختیار",
                "verbose_name_plural": "تاریخچه تفویض اختیار",
                "ordering": ("created_at", "pk"),
            },
        ),
    ]
