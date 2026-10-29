from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=30, unique=True, verbose_name="کد شرکت")),
                ("name", models.CharField(max_length=200, verbose_name="نام شرکت")),
                ("is_parent", models.BooleanField(default=False, verbose_name="شرکت مادر")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="تاریخ ایجاد")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="subsidiaries", to="organizations.company")),
            ],
            options={"verbose_name":"شرکت","verbose_name_plural":"شرکت‌ها","ordering":["name"]},
        ),
        migrations.CreateModel(
            name="Person",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("personnel_code", models.CharField(blank=True, db_index=True, max_length=50, verbose_name="کد پرسنلی")),
                ("national_id", models.CharField(db_index=True, max_length=10, verbose_name="کد ملی")),
                ("first_name", models.CharField(max_length=100, verbose_name="نام")),
                ("last_name", models.CharField(max_length=100, verbose_name="نام خانوادگی")),
                ("relationship", models.CharField(choices=[("employee","کارمند"),("spouse","همسر"),("child","فرزند"),("other","سایر افراد تحت تکفل")], default="employee", max_length=20, verbose_name="نسبت")),
                ("mobile", models.CharField(blank=True, max_length=20, verbose_name="همراه")),
                ("iban", models.CharField(blank=True, max_length=34, verbose_name="شماره شبا")),
                ("is_insured", models.BooleanField(default=True, verbose_name="تحت پوشش")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="people", to="organizations.company")),
                ("employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="dependents", to="organizations.person")),
            ],
            options={"verbose_name":"شخص بیمه‌شده","verbose_name_plural":"اشخاص بیمه‌شده","ordering":["company__name","last_name","first_name"]},
        ),
        migrations.AddConstraint(
            model_name="person",
            constraint=models.UniqueConstraint(fields=("company","national_id"), name="uniq_person_company_national_id"),
        ),
    ]
