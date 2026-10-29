from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="ServiceRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(max_length=30, unique=True, verbose_name="شماره پیگیری")),
                ("kind", models.CharField(choices=[("medical_assistance","کمک‌هزینه درمان"),("anonymous_plan","طرح بی‌نام"),("excess_coverage","مازاد تعهدات"),("identity_change","اصلاح اطلاعات هویتی"),("iban_change","اصلاح شماره شبا"),("add_coverage","افزایش افراد تحت پوشش"),("remove_coverage","کاهش افراد تحت پوشش"),("document_request","درخواست مدارک یا فرم"),("base_insurance_waiver","فرم انصراف از سهم بیمه پایه"),("other","سایر درخواست‌ها")], max_length=30, verbose_name="نوع درخواست")),
                ("title", models.CharField(max_length=250, verbose_name="عنوان")),
                ("description", models.TextField(verbose_name="شرح درخواست")),
                ("status", models.CharField(choices=[("submitted","ثبت‌شده"),("in_review","در حال بررسی"),("needs_info","نیازمند تکمیل"),("referred","ارجاع‌شده"),("approved","تأییدشده"),("rejected","ردشده"),("completed","انجام‌شده"),("closed","بسته‌شده")], default="submitted", max_length=20, verbose_name="وضعیت")),
                ("response", models.TextField(blank=True, verbose_name="پاسخ اداره بیمه")),
                ("attachment", models.FileField(blank=True, upload_to="request_files/", verbose_name="پیوست غیرپزشکی/اداری")),
                ("is_confidential", models.BooleanField(default=False, verbose_name="محرمانه")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="organizations.company")),
                ("person", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="organizations.person")),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="service_requests", to=settings.AUTH_USER_MODEL)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_service_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["-created_at"]},
        ),
    ]
