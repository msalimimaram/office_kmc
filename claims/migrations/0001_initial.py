from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings
from django.db.models import F, Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("insurance", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Claim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("claim_number", models.CharField(max_length=100, unique=True, verbose_name="شناسه خسارت")),
                ("service_date", models.DateField(blank=True, null=True, verbose_name="تاریخ خدمت")),
                ("registered_date", models.DateField(blank=True, null=True, verbose_name="تاریخ ثبت")),
                ("service_type", models.CharField(help_text="فقط نوع خدمت؛ تصویر یا محتوای مدرک پزشکی ثبت نشود.", max_length=120, verbose_name="نوع خدمت")),
                ("requested_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="مبلغ ثبت‌شده/درخواستی")),
                ("assessed_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="مبلغ تأییدشده")),
                ("payable_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="مبلغ قابل پرداخت")),
                ("paid_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="مبلغ پرداخت‌شده طبق اعلام منبع")),
                ("payment_date", models.DateField(blank=True, null=True, verbose_name="تاریخ پرداخت")),
                ("status", models.CharField(choices=[("registered","ثبت‌شده"),("under_review","در حال ارزیابی"),("needs_info","نیازمند اصلاح"),("approved","تأییدشده"),("rejected","ردشده"),("partially_paid","پرداخت بخشی"),("paid","پرداخت‌شده"),("closed","بسته‌شده")], default="registered", max_length=24, verbose_name="وضعیت")),
                ("source_reference", models.CharField(blank=True, max_length=200, verbose_name="مرجع فایل/سامانه منبع")),
                ("assessment_note", models.TextField(blank=True, verbose_name="یادداشت ارزیابی غیرپزشکی")),
                ("imported_at", models.DateTimeField(blank=True, null=True, verbose_name="آخرین ورود اطلاعات")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین بروزرسانی")),
                ("contract", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="claims", to="insurance.contract")),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="insurance.insurer")),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="claims", to="organizations.person")),
            ],
            options={"verbose_name":"خسارت","verbose_name_plural":"خسارت‌ها","ordering":["-registered_date","-created_at"]},
        ),
        migrations.CreateModel(
            name="ClaimObjection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.TextField(verbose_name="شرح اعتراض")),
                ("status", models.CharField(choices=[("open","ثبت‌شده"),("in_review","در حال بررسی"),("answered","پاسخ داده‌شده"),("closed","بسته‌شده")], default="open", max_length=20)),
                ("response", models.TextField(blank=True, verbose_name="پاسخ")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("claim", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="objections", to="claims.claim")),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(model_name="claim", constraint=models.CheckConstraint(condition=Q(requested_amount__gte=0), name="claim_requested_nonnegative")),
        migrations.AddConstraint(model_name="claim", constraint=models.CheckConstraint(condition=Q(assessed_amount__gte=0), name="claim_assessed_nonnegative")),
        migrations.AddConstraint(model_name="claim", constraint=models.CheckConstraint(condition=Q(payable_amount__gte=0), name="claim_payable_nonnegative")),
        migrations.AddConstraint(model_name="claim", constraint=models.CheckConstraint(condition=Q(paid_amount__gte=0), name="claim_paid_nonnegative")),
        migrations.AddConstraint(model_name="claim", constraint=models.CheckConstraint(condition=Q(paid_amount__lte=F("payable_amount")), name="claim_paid_lte_payable")),
    ]
