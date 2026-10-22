from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Claim(models.Model):
    class Status(models.TextChoices):
        REGISTERED = "registered", "ثبت‌شده"
        UNDER_REVIEW = "under_review", "در حال ارزیابی"
        NEEDS_INFO = "needs_info", "نیازمند اصلاح"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        PARTIALLY_PAID = "partially_paid", "پرداخت بخشی"
        PAID = "paid", "پرداخت‌شده"
        CLOSED = "closed", "بسته‌شده"

    claim_number = models.CharField("شناسه خسارت", max_length=100, unique=True)
    person = models.ForeignKey("organizations.Person", on_delete=models.PROTECT, related_name="claims")
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="claims")
    insurer = models.ForeignKey("insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT)
    service_date = models.DateField("تاریخ خدمت", null=True, blank=True)
    registered_date = models.DateField("تاریخ ثبت", null=True, blank=True)
    service_type = models.CharField("نوع خدمت", max_length=120, help_text="فقط نوع خدمت؛ تصویر یا محتوای مدرک پزشکی ثبت نشود.")
    requested_amount = models.DecimalField("مبلغ ثبت‌شده/درخواستی", max_digits=16, decimal_places=2, default=0)
    assessed_amount = models.DecimalField("مبلغ تأییدشده", max_digits=16, decimal_places=2, default=0)
    payable_amount = models.DecimalField("مبلغ قابل پرداخت", max_digits=16, decimal_places=2, default=0)
    paid_amount = models.DecimalField("مبلغ پرداخت‌شده طبق اعلام منبع", max_digits=16, decimal_places=2, default=0)
    payment_date = models.DateField("تاریخ پرداخت", null=True, blank=True)
    status = models.CharField("وضعیت", max_length=24, choices=Status.choices, default=Status.REGISTERED)
    source_reference = models.CharField("مرجع فایل/سامانه منبع", max_length=200, blank=True)
    assessment_note = models.TextField("یادداشت ارزیابی غیرپزشکی", blank=True)
    imported_at = models.DateTimeField("آخرین ورود اطلاعات", null=True, blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین بروزرسانی", auto_now=True)

    class Meta:
        ordering = ["-registered_date", "-created_at"]
        verbose_name = "خسارت"
        verbose_name_plural = "خسارت‌ها"

    def clean(self):
        super().clean()
        errors = {}
        money_fields = ("requested_amount", "assessed_amount", "payable_amount", "paid_amount")
        for field in money_fields:
            value = getattr(self, field, None)
            if value is not None and value < 0:
                errors[field] = "مبلغ نمی‌تواند منفی باشد."
        if self.paid_amount is not None and self.payable_amount is not None and self.paid_amount > self.payable_amount:
            errors["paid_amount"] = "مبلغ پرداخت‌شده نمی‌تواند از مبلغ قابل پرداخت بیشتر باشد."
        if self.payment_date and not self.paid_amount:
            errors["payment_date"] = "تاریخ پرداخت بدون مبلغ پرداخت‌شده قابل ثبت نیست."
        if self.contract_id and self.insurer_id and self.contract.insurer_id != self.insurer_id:
            errors["insurer"] = "بیمه‌گر خسارت باید با بیمه‌گر قرارداد یکسان باشد."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.claim_number


class ClaimObjection(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "ثبت‌شده"
        IN_REVIEW = "in_review", "در حال بررسی"
        ANSWERED = "answered", "پاسخ داده‌شده"
        CLOSED = "closed", "بسته‌شده"

    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="objections")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    description = models.TextField("شرح اعتراض")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    response = models.TextField("پاسخ", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
