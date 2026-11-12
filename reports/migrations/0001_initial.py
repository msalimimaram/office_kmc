from django.conf import settings
from django.db import migrations, models
import django.utils.timezone
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("organizations", "0005_person_change_request"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=240, verbose_name="عنوان گزارش")),
                ("report_type", models.CharField(choices=[("claims", "خسارت‌ها"), ("contracts", "قراردادها"), ("assets", "دارایی‌ها"), ("operations", "عملیات اداره بیمه"), ("custom", "گزارش سفارشی")], max_length=20, verbose_name="نوع گزارش")),
                ("line_code", models.CharField(choices=[("health", "درمان تکمیلی"), ("life", "عمر و حوادث"), ("liability", "مسئولیت"), ("fire", "آتش‌سوزی و اموال"), ("third_party", "شخص ثالث"), ("body", "بدنه خودرو"), ("other", "سایر")], max_length=40, verbose_name="رشته بیمه")),
                ("period_start", models.DateField(verbose_name="شروع دوره گزارش")),
                ("period_end", models.DateField(verbose_name="پایان دوره گزارش")),
                ("status", models.CharField(choices=[("draft", "پیش‌نویس"), ("supervisor_review", "بررسی سرپرست"), ("responsible_review", "بررسی مسئول"), ("head_review", "بررسی رئیس اداره"), ("returned", "بازگشت برای اصلاح"), ("approved", "تأییدشده"), ("rejected", "ردشده"), ("closed", "مختومه")], default="draft", max_length=24, verbose_name="وضعیت")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="management_reports_assigned", to=settings.AUTH_USER_MODEL)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="management_reports", to="organizations.company")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="management_reports_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "گزارش مدیریتی", "verbose_name_plural": "گزارش‌های مدیریتی", "ordering": ("-updated_at", "-pk")},
        ),
        migrations.CreateModel(
            name="ReportVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version_number", models.PositiveIntegerField(verbose_name="شماره نسخه")),
                ("summary", models.TextField(max_length=3000, verbose_name="خلاصه مدیریتی")),
                ("body", models.TextField(verbose_name="متن گزارش")),
                ("filters_snapshot", models.JSONField(blank=True, default=dict, verbose_name="فیلترهای مبنای گزارش")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="management_report_versions_created", to=settings.AUTH_USER_MODEL)),
                ("report", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="reports.report")),
            ],
            options={"verbose_name": "نسخه گزارش", "verbose_name_plural": "نسخه‌های گزارش", "ordering": ("-version_number", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="report",
            constraint=models.CheckConstraint(condition=models.Q(("period_end__gte", models.F("period_start"))), name="report_period_valid"),
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(fields=["line_code", "status"], name="report_line_status"),
        ),
        migrations.AddIndex(
            model_name="report",
            index=models.Index(fields=["assigned_to", "status"], name="report_assignee_status"),
        ),
        migrations.AddConstraint(
            model_name="reportversion",
            constraint=models.UniqueConstraint(fields=("report", "version_number"), name="uniq_report_version"),
        ),
        migrations.AddConstraint(
            model_name="reportversion",
            constraint=models.CheckConstraint(condition=models.Q(("version_number__gte", 1)), name="report_version_positive"),
        ),
    ]
