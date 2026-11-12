from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from insurance.models import InsuranceLine
from organizations.models import Company


class Report(models.Model):
    class Type(models.TextChoices):
        CLAIMS = "claims", "خسارت‌ها"
        CONTRACTS = "contracts", "قراردادها"
        ASSETS = "assets", "دارایی‌ها"
        OPERATIONS = "operations", "عملیات اداره بیمه"
        CUSTOM = "custom", "گزارش سفارشی"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        SUPERVISOR_REVIEW = "supervisor_review", "بررسی سرپرست"
        RESPONSIBLE_REVIEW = "responsible_review", "بررسی مسئول"
        HEAD_REVIEW = "head_review", "بررسی رئیس اداره"
        RETURNED = "returned", "بازگشت برای اصلاح"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        CLOSED = "closed", "مختومه"

    title = models.CharField("عنوان گزارش", max_length=240)
    report_type = models.CharField("نوع گزارش", max_length=20, choices=Type.choices)
    line_code = models.CharField("رشته بیمه", max_length=40, choices=InsuranceLine.choices)
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT,
        related_name="management_reports",
    )
    period_start = models.DateField("شروع دوره گزارش")
    period_end = models.DateField("پایان دوره گزارش")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="management_reports_created",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="management_reports_assigned",
    )
    status = models.CharField(
        "وضعیت", max_length=24, choices=Status.choices, default=Status.DRAFT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-pk")
        indexes = [
            models.Index(fields=("line_code", "status"), name="report_line_status"),
            models.Index(fields=("assigned_to", "status"), name="report_assignee_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="report_period_valid",
            ),
        ]
        verbose_name = "گزارش مدیریتی"
        verbose_name_plural = "گزارش‌های مدیریتی"

    def clean(self):
        super().clean()
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValidationError({"period_end": "پایان دوره گزارش نمی‌تواند قبل از شروع آن باشد."})
        if self.line_code and self.line_code not in dict(InsuranceLine.choices):
            raise ValidationError({"line_code": "رشته بیمه معتبر نیست."})
        if self.company_id and not self.company.is_active:
            raise ValidationError({"company": "گزارش جدید برای شرکت غیرفعال مجاز نیست."})

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_workflow_sync", False):
            previous = type(self)._base_manager.filter(pk=self.pk).values_list("status", flat=True).first()
            if previous is not None and previous != self.status:
                raise ValidationError("تغییر وضعیت گزارش فقط از مسیر گردش‌کار مجاز است.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        target = self.Status.CLOSED if closed else step_code
        if target not in self.Status.values or self.status == target:
            return
        self.status = target
        self._workflow_sync = True
        self.save(update_fields=["status", "updated_at"])

    def sync_workflow_assignee(self, *, assignee):
        if self.assigned_to_id == getattr(assignee, "pk", None):
            return
        self.assigned_to = assignee
        self.save(update_fields=["assigned_to", "updated_at"])

    @property
    def latest_version(self):
        return self.versions.order_by("-version_number", "-pk").first()

    def __str__(self):
        return self.title


class ImmutableReportVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("نسخه گزارش غیرقابل ویرایش است؛ نسخه جدید ایجاد کنید.")

    def delete(self):
        raise ValidationError("نسخه گزارش حذف نمی‌شود.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی نسخه گزارش مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی نسخه گزارش خارج از سرویس مجاز نیست.")


class ReportVersion(models.Model):
    objects = ImmutableReportVersionQuerySet.as_manager()

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField("شماره نسخه")
    summary = models.TextField("خلاصه مدیریتی", max_length=3000)
    body = models.TextField("متن گزارش")
    filters_snapshot = models.JSONField("فیلترهای مبنای گزارش", default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="management_report_versions_created",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-version_number", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("report", "version_number"), name="uniq_report_version"),
            models.CheckConstraint(condition=models.Q(version_number__gte=1), name="report_version_positive"),
        ]
        verbose_name = "نسخه گزارش"
        verbose_name_plural = "نسخه‌های گزارش"

    def clean(self):
        super().clean()
        if self.version_number < 1:
            raise ValidationError({"version_number": "شماره نسخه باید حداقل یک باشد."})
        if not self.summary.strip() or not self.body.strip():
            raise ValidationError("خلاصه و متن گزارش الزامی است.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("نسخه ثبت‌شده گزارش غیرقابل ویرایش است.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("نسخه گزارش حذف نمی‌شود.")
