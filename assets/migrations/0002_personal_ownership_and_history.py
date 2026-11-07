from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_asset_history(apps, schema_editor):
    Asset = apps.get_model("assets", "InsuredAsset")
    Valuation = apps.get_model("assets", "AssetValuation")
    PolicyPeriod = apps.get_model("assets", "AssetPolicyPeriod")
    db = schema_editor.connection.alias

    for asset in Asset.objects.using(db).all().iterator():
        if asset.insured_value and asset.insured_value > 0:
            Valuation.objects.using(db).get_or_create(
                asset_id=asset.pk,
                method="legacy_snapshot",
                defaults={
                    "valuation_date": None,
                    "market_value": 0,
                    "insured_value": asset.insured_value,
                    "source_reference": "legacy_asset_snapshot",
                    "note": "انتقال مقدار فعلی از ساختار قدیمی؛ تاریخ ارزیابی قبلی مشخص نبوده است.",
                    "created_by_id": asset.created_by_id,
                },
            )
        if asset.policy_number and asset.insurer_id:
            PolicyPeriod.objects.using(db).get_or_create(
                asset_id=asset.pk,
                policy_number=asset.policy_number,
                defaults={
                    "insurer_id": asset.insurer_id,
                    "contract_id": asset.contract_id,
                    "policy_start": asset.policy_start,
                    "policy_end": asset.policy_end,
                    "status": "active" if asset.is_active else "draft",
                    "source_reference": "legacy_asset_policy_snapshot",
                    "note": "انتقال مشخصات بیمه‌نامه از ساختار قدیمی.",
                    "created_by_id": asset.created_by_id,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0001_initial"),
        ("organizations", "0002_person_identity_and_employment"),
        ("accounts", "0003_role_assignment_foundation"),
        ("insurance", "0002_contractrevision"),
    ]

    operations = [
        migrations.AlterField(
            model_name="insuredasset",
            name="company",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="insured_assets", to="organizations.company"),
        ),
        migrations.AddField(
            model_name="insuredasset",
            name="person",
            field=models.ForeignKey(blank=True, help_text="برای دارایی شخصی؛ برای دارایی شرکتی خالی باشد.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="insured_assets", to="organizations.person"),
        ),
        migrations.AddConstraint(
            model_name="insuredasset",
            constraint=models.CheckConstraint(
                condition=(models.Q(company__isnull=False, person__isnull=True) | models.Q(company__isnull=True, person__isnull=False)),
                name="insured_asset_single_owner",
            ),
        ),
        migrations.CreateModel(
            name="AssetValuation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valuation_date", models.DateField(blank=True, null=True, verbose_name="تاریخ ارزیابی")),
                ("market_value", models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name="ارزش روز")),
                ("insured_value", models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name="ارزش بیمه‌شده")),
                ("method", models.CharField(choices=[("formal", "ارزیابی رسمی"), ("expert", "نظر کارشناس"), ("declared", "اظهار واحد"), ("legacy_snapshot", "انتقال از اطلاعات قدیمی")], default="expert", max_length=24, verbose_name="روش ارزیابی")),
                ("source_reference", models.CharField(blank=True, max_length=160, verbose_name="مرجع ارزیابی")),
                ("note", models.TextField(blank=True, verbose_name="توضیحات")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_asset_valuations", to=settings.AUTH_USER_MODEL)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="valuations", to="assets.insuredasset")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_valuations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "ارزیابی دارایی", "verbose_name_plural": "سوابق ارزیابی دارایی", "ordering": ("asset_id", "-valuation_date", "-created_at")},
        ),
        migrations.CreateModel(
            name="AssetPolicyPeriod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("policy_number", models.CharField(max_length=100, verbose_name="شماره بیمه‌نامه")),
                ("policy_start", models.DateField(blank=True, null=True, verbose_name="شروع پوشش")),
                ("policy_end", models.DateField(blank=True, null=True, verbose_name="پایان پوشش")),
                ("status", models.CharField(choices=[("draft", "پیش‌نویس"), ("active", "فعال"), ("expired", "منقضی"), ("terminated", "فسخ‌شده"), ("superseded", "جایگزین‌شده")], default="draft", max_length=16, verbose_name="وضعیت")),
                ("source_reference", models.CharField(blank=True, max_length=160, verbose_name="مرجع منبع")),
                ("note", models.TextField(blank=True, verbose_name="توضیحات")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_policy_periods_approved", to=settings.AUTH_USER_MODEL)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="policy_periods", to="assets.insuredasset")),
                ("contract", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="asset_policy_periods", to="insurance.contract")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_policy_periods_created", to=settings.AUTH_USER_MODEL)),
                ("insurer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="asset_policy_periods", to="insurance.insurer")),
            ],
            options={"verbose_name": "دوره بیمه‌نامه دارایی", "verbose_name_plural": "دوره‌های بیمه‌نامه دارایی", "ordering": ("asset_id", "-policy_start", "-created_at")},
        ),
        migrations.CreateModel(
            name="AssetPolicyEndorsement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endorsement_number", models.CharField(max_length=100, verbose_name="شماره الحاقیه")),
                ("effective_date", models.DateField(blank=True, null=True, verbose_name="تاریخ اثر")),
                ("description", models.TextField(verbose_name="شرح تغییر")),
                ("document", models.FileField(upload_to="asset_endorsements/", verbose_name="فایل الحاقیه")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_asset_endorsements", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("policy_period", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="endorsements", to="assets.assetpolicyperiod")),
            ],
            options={"verbose_name": "الحاقیه بیمه‌نامه دارایی", "verbose_name_plural": "الحاقیه‌های بیمه‌نامه دارایی"},
        ),
        migrations.AddConstraint(
            model_name="assetvaluation",
            constraint=models.CheckConstraint(condition=models.Q(market_value__gte=0), name="asset_market_value_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="assetvaluation",
            constraint=models.CheckConstraint(condition=models.Q(insured_value__gte=0), name="asset_valuation_insured_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="assetpolicyperiod",
            constraint=models.CheckConstraint(condition=models.Q(policy_end__isnull=True) | models.Q(policy_start__isnull=True) | models.Q(policy_end__gte=models.F("policy_start")), name="asset_policy_period_dates"),
        ),
        migrations.AddConstraint(
            model_name="assetpolicyendorsement",
            constraint=models.UniqueConstraint(fields=("policy_period", "endorsement_number"), name="uniq_asset_policy_endorsement"),
        ),
        migrations.RunPython(backfill_asset_history, migrations.RunPython.noop),
    ]
