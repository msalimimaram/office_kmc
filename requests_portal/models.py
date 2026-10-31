from django.db import models
from django.conf import settings


class ServiceRequest(models.Model):
    class Kind(models.TextChoices):
        MEDICAL_ASSISTANCE = "medical_assistance", "کمک‌هزینه درمان"
        ANONYMOUS_PLAN = "anonymous_plan", "طرح بی‌نام"
        EXCESS_COVERAGE = "excess_coverage", "مازاد تعهدات"
        IDENTITY_CHANGE = "identity_change", "اصلاح اطلاعات هویتی"
        IBAN_CHANGE = "iban_change", "اصلاح شماره شبا"
        ADD_COVERAGE = "add_coverage", "افزایش افراد تحت پوشش"
        REMOVE_COVERAGE = "remove_coverage", "کاهش افراد تحت پوشش"
        DOCUMENT_REQUEST = "document_request", "درخواست مدارک یا فرم"
        BASE_INSURANCE_WAIVER = "base_insurance_waiver", "فرم انصراف از سهم بیمه پایه"
        OTHER = "other", "سایر درخواست‌ها"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "ثبت‌شده"
        IN_REVIEW = "in_review", "در حال بررسی"
        NEEDS_INFO = "needs_info", "نیازمند تکمیل"
        REFERRED = "referred", "ارجاع‌شده"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        COMPLETED = "completed", "انجام‌شده"
        CLOSED = "closed", "بسته‌شده"

    reference = models.CharField("شماره پیگیری", max_length=30, unique=True)
    kind = models.CharField("نوع درخواست", max_length=30, choices=Kind.choices)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="service_requests")
    person = models.ForeignKey("organizations.Person", null=True, blank=True, on_delete=models.PROTECT)
    company = models.ForeignKey("organizations.Company", null=True, blank=True, on_delete=models.PROTECT)
    title = models.CharField("عنوان", max_length=250)
    description = models.TextField("شرح درخواست")
    status = models.CharField("وضعیت", max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_service_requests")
    response = models.TextField("پاسخ اداره بیمه", blank=True)
    attachment = models.FileField("پیوست غیرپزشکی/اداری", upload_to="request_files/", blank=True)
    is_confidential = models.BooleanField("محرمانه", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(kind="medical_assistance") | models.Q(is_confidential=True),
                name="svc_medical_confidential",
            ),
        ]

    def clean(self):
        super().clean()
        if self.kind == self.Kind.MEDICAL_ASSISTANCE:
            self.is_confidential = True

    def save(self, *args, **kwargs):
        # Enforce confidentiality for every normal model save, including admin edits.
        if self.kind == self.Kind.MEDICAL_ASSISTANCE:
            self.is_confidential = True
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.title}"
