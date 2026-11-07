from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_primary_insured_and_payments(apps, schema_editor):
    Claim = apps.get_model("claims", "Claim")
    ClaimPayment = apps.get_model("claims", "ClaimPayment")
    db = schema_editor.connection.alias

    for claim in Claim.objects.using(db).select_related("person").all().iterator():
        primary_id = claim.person.employee_id or claim.person_id
        if not claim.primary_insured_id:
            Claim.objects.using(db).filter(pk=claim.pk).update(primary_insured_id=primary_id)
        if claim.paid_amount and claim.paid_amount > 0:
            ClaimPayment.objects.using(db).get_or_create(
                claim_id=claim.pk,
                is_legacy_import=True,
                defaults={
                    "amount": claim.paid_amount,
                    "paid_at": claim.payment_date,
                    "source_reference": claim.source_reference or "legacy_paid_amount",
                    "source_insurer_id": claim.insurer_id,
                    "note": "انتقال مبلغ تجمیعی پرداخت‌شده از ساختار قدیمی؛ رکورد اصلی حفظ شده است.",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("claims", "0001_initial"),
        ("organizations", "0002_person_identity_and_employment"),
        ("accounts", "0003_role_assignment_foundation"),
        ("insurance", "0002_contractrevision"),
    ]

    operations = [
        migrations.AddField(
            model_name="claim",
            name="source_claim_number",
            field=models.CharField(blank=True, db_index=True, max_length=120, verbose_name="شماره پرونده در سامانه بیمه‌گر"),
        ),
        migrations.AddField(
            model_name="claim",
            name="primary_insured",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="primary_insured_claims", to="organizations.person"),
        ),
        migrations.AddField(
            model_name="claim",
            name="company_snapshot",
            field=models.ForeignKey(blank=True, help_text="شرکت مرتبط در زمان وقوع/ثبت خسارت؛ برای حفظ تاریخچه پس از انتقال شخص.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="claim_snapshots", to="organizations.company"),
        ),
        migrations.AddField(
            model_name="claim",
            name="source_registered_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ ثبت در بیمه‌گر"),
        ),
        migrations.AddField(
            model_name="claim",
            name="contract_number_snapshot",
            field=models.CharField(blank=True, max_length=120, verbose_name="شماره قرارداد در منبع"),
        ),
        migrations.AddField(
            model_name="claim",
            name="source_duplicate_status",
            field=models.CharField(choices=[("not_declared", "اعلام نشده"), ("declared_duplicate", "تکراری اعلام‌شده توسط بیمه‌گر")], default="not_declared", max_length=24, verbose_name="وضعیت تکراری طبق اعلام بیمه‌گر"),
        ),
        migrations.AddField(
            model_name="claim",
            name="source_duplicate_reference",
            field=models.CharField(blank=True, max_length=120, verbose_name="مرجع خسارت اصلی اعلام‌شده"),
        ),
        migrations.AddField(
            model_name="claim",
            name="source_duplicate_note",
            field=models.TextField(blank=True, verbose_name="توضیح اعلام تکراری بودن"),
        ),
        migrations.AddField(
            model_name="claim",
            name="source_duplicate_reported_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان اعلام تکراری بودن"),
        ),
        migrations.AddField(
            model_name="claim",
            name="result_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان ارسال نتیجه به بیمه‌شده"),
        ),
        migrations.AddField(
            model_name="claim",
            name="result_sent_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="sent_claim_results", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="ClaimPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16, verbose_name="مبلغ پرداخت")),
                ("entry_type", models.CharField(choices=[("payment", "پرداخت ثبت‌شده"), ("reversal", "برگشت/اصلاح پرداخت")], default="payment", max_length=12, verbose_name="نوع رویداد")),
                ("paid_at", models.DateField(blank=True, null=True, verbose_name="تاریخ پرداخت")),
                ("source_reference", models.CharField(blank=True, max_length=160, verbose_name="شماره حواله/مرجع منبع")),
                ("note", models.TextField(blank=True, verbose_name="توضیحات")),
                ("is_legacy_import", models.BooleanField(default=False, verbose_name="منتقل‌شده از داده قدیمی")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ثبت")),
                ("claim", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="claims.claim")),
                ("reverses_payment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="reversal_entries", to="claims.claimpayment")),
                ("confirmed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="confirmed_claim_payments", to=settings.AUTH_USER_MODEL)),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="recorded_claim_payments", to=settings.AUTH_USER_MODEL)),
                ("source_insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="claim_payments", to="insurance.insurer")),
            ],
            options={"verbose_name": "مرحله پرداخت خسارت", "verbose_name_plural": "مراحل پرداخت خسارت", "ordering": ("claim_id", "paid_at", "created_at", "pk")},
        ),
        migrations.AddField(
            model_name="claimobjection",
            name="deadline_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="آخرین مهلت ثبت اعتراض"),
        ),
        migrations.AddConstraint(
            model_name="claim",
            constraint=models.CheckConstraint(
                condition=~models.Q(source_duplicate_status="declared_duplicate") | models.Q(insurer__isnull=False),
                name="claim_duplicate_requires_insurer",
            ),
        ),
        migrations.AddConstraint(
            model_name="claimpayment",
            constraint=models.CheckConstraint(condition=models.Q(amount__gt=0), name="claim_payment_amount_positive"),
        ),
        migrations.AddConstraint(
            model_name="claimpayment",
            constraint=models.CheckConstraint(
                condition=(models.Q(entry_type="payment", reverses_payment__isnull=True)
                           | models.Q(entry_type="reversal", reverses_payment__isnull=False)),
                name="claim_payment_reversal_target",
            ),
        ),
        migrations.AddIndex(
            model_name="claim",
            index=models.Index(fields=["company_snapshot", "registered_date"], name="claim_company_regdate"),
        ),
        migrations.AddIndex(
            model_name="claim",
            index=models.Index(fields=["insurer", "source_claim_number"], name="claim_insurer_source_ref"),
        ),
        migrations.AddIndex(
            model_name="claim",
            index=models.Index(fields=["primary_insured", "service_date"], name="claim_primary_service"),
        ),
        migrations.RunPython(backfill_primary_insured_and_payments, migrations.RunPython.noop),
    ]
