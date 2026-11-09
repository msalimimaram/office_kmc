from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0004_alter_person_options"),
        ("insurance", "0003_contract_lifecycle"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonChangeRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("change_type", models.CharField(
                    choices=[
                        ("mobile", "شماره همراه"),
                        ("iban", "شماره شبا"),
                        ("national_id", "کد ملی"),
                        ("first_name", "نام"),
                        ("last_name", "نام خانوادگی"),
                        ("personnel_code", "کد پرسنلی"),
                        ("birth_date", "تاریخ تولد"),
                    ],
                    max_length=24,
                    verbose_name="نوع تغییر",
                )),
                ("current_value", models.CharField(blank=True, max_length=160, verbose_name="مقدار ثبت‌شده هنگام درخواست")),
                ("requested_value", models.CharField(max_length=160, verbose_name="مقدار درخواستی")),
                ("reason", models.TextField(max_length=2000, verbose_name="دلیل و توضیحات")),
                ("status", models.CharField(
                    choices=[
                        ("submitted", "ثبت‌شده"),
                        ("company_review", "بررسی نماینده شرکت"),
                        ("insurer_update", "اقدام بیمه‌گر"),
                        ("company_final_review", "بازبینی نهایی نماینده شرکت"),
                        ("approved", "تأیید و اعمال‌شده"),
                        ("rejected", "ردشده"),
                    ],
                    default="submitted",
                    max_length=32,
                    verbose_name="وضعیت",
                )),
                ("approved_at", models.DateTimeField(blank=True, null=True, verbose_name="زمان تأیید نهایی")),
                ("rejected_at", models.DateTimeField(blank=True, null=True, verbose_name="زمان رد")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="approved_person_change_requests",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("company", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="person_change_requests",
                    to="organizations.company",
                    verbose_name="شرکت در زمان درخواست",
                )),
                ("contract", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="person_change_requests",
                    to="insurance.contract",
                    verbose_name="قرارداد/بیمه‌گر مرتبط",
                )),
                ("person", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="change_requests",
                    to="organizations.person",
                    verbose_name="شخص",
                )),
                ("rejected_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="rejected_person_change_requests",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("requested_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="person_change_requests",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="درخواست‌کننده",
                )),
            ],
            options={
                "verbose_name": "درخواست تغییر اطلاعات بیمه‌شده",
                "verbose_name_plural": "درخواست‌های تغییر اطلاعات بیمه‌شدگان",
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="personchangerequest",
            constraint=models.UniqueConstraint(
                fields=("person", "change_type"),
                condition=models.Q(status__in=[
                    "submitted", "company_review", "insurer_update", "company_final_review"
                ]),
                name="uniq_open_person_change_field",
            ),
        ),
        migrations.AddIndex(
            model_name="personchangerequest",
            index=models.Index(fields=["company", "status", "created_at"], name="person_change_company_status"),
        ),
        migrations.AddIndex(
            model_name="personchangerequest",
            index=models.Index(fields=["requested_by", "created_at"], name="person_change_requester"),
        ),
    ]
