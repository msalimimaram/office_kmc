from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F, Q

class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("insurance", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="InsuredAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asset_code", models.CharField(max_length=80, unique=True, verbose_name="کد دارایی")),
                ("name", models.CharField(max_length=250, verbose_name="عنوان دارایی")),
                ("asset_type", models.CharField(choices=[("vehicle","خودرو"),("property","ساختمان و ملک"),("equipment","تجهیزات"),("other","سایر دارایی‌ها")], max_length=20, verbose_name="نوع دارایی")),
                ("identifier", models.CharField(blank=True, max_length=120, verbose_name="شناسه ثبتی/داخلی")),
                ("location", models.CharField(blank=True, max_length=250, verbose_name="محل استقرار")),
                ("insured_value", models.DecimalField(decimal_places=2, default=0, max_digits=18, verbose_name="ارزش بیمه‌شده")),
                ("policy_number", models.CharField(blank=True, max_length=100, verbose_name="شماره بیمه‌نامه")),
                ("policy_start", models.DateField(blank=True, null=True, verbose_name="شروع پوشش")),
                ("policy_end", models.DateField(blank=True, null=True, verbose_name="پایان پوشش")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("notes", models.TextField(blank=True, verbose_name="توضیحات")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ثبت")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="insured_assets", to="organizations.company")),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="insured_assets", to="insurance.insurer")),
                ("contract", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="insured_assets", to="insurance.contract")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="registered_assets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["company__name","asset_type","name"],"verbose_name":"دارایی بیمه‌شده","verbose_name_plural":"دارایی‌های بیمه‌شده"},
        ),
        migrations.CreateModel(
            name="Vehicle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plate_number", models.CharField(max_length=40, verbose_name="شماره پلاک")),
                ("vin", models.CharField(blank=True, db_index=True, max_length=80, verbose_name="شماره شاسی/VIN")),
                ("engine_number", models.CharField(blank=True, max_length=80, verbose_name="شماره موتور")),
                ("make", models.CharField(blank=True, max_length=100, verbose_name="سازنده")),
                ("model_name", models.CharField(blank=True, max_length=100, verbose_name="مدل")),
                ("model_year", models.PositiveSmallIntegerField(blank=True, null=True, verbose_name="سال ساخت")),
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="vehicle_details", to="assets.insuredasset")),
            ],
            options={"verbose_name":"مشخصات خودرو","verbose_name_plural":"مشخصات خودروها"},
        ),
        migrations.AddConstraint(model_name="insuredasset", constraint=models.CheckConstraint(condition=Q(insured_value__gte=0), name="insured_asset_value_nonnegative")),
        migrations.AddConstraint(model_name="insuredasset", constraint=models.CheckConstraint(condition=Q(policy_end__isnull=True) | Q(policy_start__isnull=True) | Q(policy_end__gte=F("policy_start")), name="insured_asset_policy_dates_ordered")),
    ]
