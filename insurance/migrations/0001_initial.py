from django.db import migrations, models
import django.db.models.deletion
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Insurer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, unique=True, verbose_name="نام بیمه‌گر")),
                ("contact_name", models.CharField(blank=True, max_length=150, verbose_name="شخص تماس")),
                ("contact_email", models.EmailField(blank=True, max_length=254, verbose_name="ایمیل")),
                ("contact_phone", models.CharField(blank=True, max_length=40, verbose_name="تلفن")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
            ],
        ),
        migrations.CreateModel(
            name="Contract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=80, unique=True, verbose_name="شماره قرارداد")),
                ("title", models.CharField(max_length=250, verbose_name="عنوان قرارداد")),
                ("line", models.CharField(choices=[("health","درمان تکمیلی"),("life","عمر و حوادث"),("liability","مسئولیت"),("fire","آتش‌سوزی و اموال"),("third_party","شخص ثالث"),("body","بدنه خودرو"),("other","سایر")], max_length=30, verbose_name="رشته بیمه")),
                ("start_date", models.DateField(verbose_name="شروع قرارداد")),
                ("end_date", models.DateField(verbose_name="پایان قرارداد")),
                ("coverage_summary", models.TextField(blank=True, verbose_name="خلاصه پوشش‌ها")),
                ("terms", models.TextField(blank=True, verbose_name="شرایط و استثناها")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("insurer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="contracts", to="insurance.insurer")),
                ("companies", models.ManyToManyField(blank=True, related_name="insurance_contracts", to="organizations.company")),
            ],
        ),
        migrations.AddConstraint(
            model_name="contract",
            constraint=models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="contract_end_on_or_after_start"),
        ),
    ]
