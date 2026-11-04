from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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

    class DuplicateStatus(models.TextChoices):
        NOT_DECLARED = "not_declared", "اعلام نشده"
        DECLARED_DUPLICATE = "declared_duplicate", "تکراری اعلام‌شده توسط بیمه‌گر"

    claim_number = models.CharField("شناسه داخلی خسارت", max_length=100, unique=True)
    source_claim_number = models.CharField("شماره پرونده در سامانه بیمه‌گر", max_length=120, blank=True, db_index=True)
    person = models.ForeignKey("organizations.Person", on_delete=models.PROTECT, related_name="claims")
    primary_insured = models.ForeignKey(
        "organizations.Person", null=True, blank=True, on_delete=models.PROTECT,
        related_name="primary_insured_claims",
    )
    company_snapshot = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="claim_snapshots",
        help_text="شرکت مرتبط در زمان وقوع/ثبت خسارت؛ برای حفظ تاریخچه پس از انتقال شخص.",
    )
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="claims")
    insurer = models.ForeignKey("insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT)
    service_date = models.DateField("تاریخ خسارت/خدمت", null=True, blank=True)
    registered_date = models.DateField("تاریخ ثبت", null=True, blank=True)
    source_registered_date = models.DateField("تاریخ ثبت در بیمه‌گر", null=True, blank=True)
    contract_number_snapshot = models.CharField("شماره قرارداد در منبع", max_length=120, blank=True)
    service_type = models.CharField("نوع خدمت", max_length=120, help_text="نوع خدمت و اطلاعات غیرپزشکی؛ دسترسی به اسناد پزشکی تابع سطح محرمانگی است.")
    requested_amount = models.DecimalField("مبلغ ثبت‌شده/درخواستی", max_digits=16, decimal_places=2, default=0)
    assessed_amount = models.DecimalField("مبلغ تأییدشده", max_digits=16, decimal_places=2, default=0)
    payable_amount = models.DecimalField("مبلغ قابل پرداخت", max_digits=16, decimal_places=2, default=0)
    paid_amount = models.DecimalField("مبلغ پرداخت‌شده طبق اعلام منبع (مقدار تجمیعی سازگاری)", max_digits=16, decimal_places=2, default=0)
    payment_date = models.DateField("آخرین تاریخ پرداخت قدیمی", null=True, blank=True)
    status = models.CharField("وضعیت", max_length=24, choices=Status.choices, default=Status.REGISTERED)
    source_reference = models.CharField("مرجع فایل/سامانه منبع", max_length=200, blank=True)
    source_duplicate_status = models.CharField(
        "وضعیت تکراری طبق اعلام بیمه‌گر",
        max_length=24,
        choices=DuplicateStatus.choices,
        default=DuplicateStatus.NOT_DECLARED,
    )
    source_duplicate_reference = models.CharField("مرجع خسارت اصلی اعلام‌شده", max_length=120, blank=True)
    source_duplicate_note = models.TextField("توضیح اعلام تکراری بودن", blank=True)
    source_duplicate_reported_at = models.DateTimeField("زمان اعلام تکراری بودن", null=True, blank=True)
    assessment_note = models.TextField("یادداشت ارزیابی غیرپزشکی", blank=True)
    result_sent_at = models.DateTimeField("زمان ارسال نتیجه به بیمه‌شده", null=True, blank=True)
    result_sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="sent_claim_results",
    )
    imported_at = models.DateTimeField("آخرین ورود اطلاعات", null=True, blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین بروزرسانی", auto_now=True)

    class Meta:
        ordering = ["-registered_date", "-created_at"]
        verbose_name = "خسارت"
        verbose_name_plural = "خسارت‌ها"
        constraints = [
            models.CheckConstraint(condition=models.Q(requested_amount__gte=0), name="claim_requested_nonnegative"),
            models.CheckConstraint(condition=models.Q(assessed_amount__gte=0), name="claim_assessed_nonnegative"),
            models.CheckConstraint(condition=models.Q(payable_amount__gte=0), name="claim_payable_nonnegative"),
            models.CheckConstraint(condition=models.Q(paid_amount__gte=0), name="claim_paid_nonnegative"),
            models.CheckConstraint(condition=models.Q(paid_amount__lte=models.F("payable_amount")), name="claim_paid_lte_payable"),
            models.CheckConstraint(
                condition=~models.Q(source_duplicate_status="declared_duplicate")
                | models.Q(insurer__isnull=False),
                name="claim_duplicate_requires_insurer",
            ),
        ]
        indexes = [
            models.Index(fields=("company_snapshot", "registered_date"), name="claim_company_regdate"),
            models.Index(fields=("insurer", "source_claim_number"), name="claim_insurer_source_ref"),
            models.Index(fields=("primary_insured", "service_date"), name="claim_primary_service"),
        ]

    @property
    def objection_deadline(self):
        return self.result_sent_at + timedelta(days=60) if self.result_sent_at else None

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
        if self.source_duplicate_status == self.DuplicateStatus.DECLARED_DUPLICATE and not self.insurer_id:
            errors["insurer"] = "اعلام تکراری بودن باید به بیمه‌گر منبع متصل باشد."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.person_id:
            if not self.primary_insured_id:
                self.primary_insured = self.person.employee if self.person.employee_id else self.person
            if not self.company_snapshot_id and self.person.company_id:
                self.company_snapshot_id = self.person.company_id
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.claim_number


class ClaimPayment(models.Model):
    """An immutable-by-history instalment reported as paid by a trusted source."""

    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField("مبلغ پرداخت", max_digits=16, decimal_places=2)
    paid_at = models.DateField("تاریخ پرداخت", null=True, blank=True)
    source_reference = models.CharField("شماره حواله/مرجع منبع", max_length=160, blank=True)
    source_insurer = models.ForeignKey(
        "insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT,
        related_name="claim_payments",
    )
    note = models.TextField("توضیحات", blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="recorded_claim_payments",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="confirmed_claim_payments",
    )
    is_legacy_import = models.BooleanField("منتقل‌شده از داده قدیمی", default=False)
    created_at = models.DateTimeField("ثبت", auto_now_add=True)

    class Meta:
        ordering = ("claim_id", "paid_at", "created_at", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="claim_payment_amount_positive"),
        ]
        verbose_name = "مرحله پرداخت خسارت"
        verbose_name_plural = "مراحل پرداخت خسارت"

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount <= 0:
            raise ValidationError({"amount": "مبلغ هر مرحله پرداخت باید بزرگ‌تر از صفر باشد."})
        if self.claim_id and self.source_insurer_id and self.claim.insurer_id and self.source_insurer_id != self.claim.insurer_id:
            raise ValidationError({"source_insurer": "بیمه‌گر پرداخت با بیمه‌گر خسارت مطابقت ندارد."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("سوابق پرداخت حذف نمی‌شوند؛ برای اصلاح، رکورد اصلاحی ثبت کنید.")

    def __str__(self):
        return f"{self.claim} — {self.amount}"


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
    deadline_at = models.DateTimeField("آخرین مهلت ثبت اعتراض", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.claim_id and self.claim.result_sent_at:
            expected = self.claim.result_sent_at + timedelta(days=60)
            if self.deadline_at and self.deadline_at != expected:
                raise ValidationError({"deadline_at": "مهلت اعتراض باید ۶۰ روز از زمان ارسال نتیجه باشد."})

    def save(self, *args, **kwargs):
        if self.claim_id and self.claim.result_sent_at and not self.deadline_at:
            self.deadline_at = self.claim.result_sent_at + timedelta(days=60)
        self.full_clean()
        return super().save(*args, **kwargs)
