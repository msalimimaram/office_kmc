from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class InsuredAsset(models.Model):
    class Type(models.TextChoices):
        VEHICLE = "vehicle", "خودرو"
        PROPERTY = "property", "ساختمان و ملک"
        EQUIPMENT = "equipment", "تجهیزات"
        OTHER = "other", "سایر دارایی‌ها"

    asset_code = models.CharField("کد دارایی", max_length=80, unique=True)
    name = models.CharField("عنوان دارایی", max_length=250)
    asset_type = models.CharField("نوع دارایی", max_length=20, choices=Type.choices)
    company = models.ForeignKey("organizations.Company", on_delete=models.PROTECT, related_name="insured_assets")
    identifier = models.CharField("شناسه ثبتی/داخلی", max_length=120, blank=True)
    location = models.CharField("محل استقرار", max_length=250, blank=True)
    insured_value = models.DecimalField("ارزش بیمه‌شده", max_digits=18, decimal_places=2, default=0)
    insurer = models.ForeignKey("insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT, related_name="insured_assets")
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="insured_assets")
    policy_number = models.CharField("شماره بیمه‌نامه", max_length=100, blank=True)
    policy_start = models.DateField("شروع پوشش", null=True, blank=True)
    policy_end = models.DateField("پایان پوشش", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    notes = models.TextField("توضیحات", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="registered_assets")
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین بروزرسانی", auto_now=True)

    class Meta:
        ordering = ["company__name", "asset_type", "name"]
        verbose_name = "دارایی بیمه‌شده"
        verbose_name_plural = "دارایی‌های بیمه‌شده"
        constraints = [
            models.CheckConstraint(condition=models.Q(insured_value__gte=0), name="insured_asset_value_nonnegative"),
            models.CheckConstraint(
                condition=models.Q(policy_end__isnull=True) | models.Q(policy_start__isnull=True) | models.Q(policy_end__gte=models.F("policy_start")),
                name="insured_asset_policy_dates_ordered",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.insured_value is not None and self.insured_value < 0:
            errors["insured_value"] = "ارزش بیمه‌شده نمی‌تواند منفی باشد."
        if self.policy_start and self.policy_end and self.policy_end < self.policy_start:
            errors["policy_end"] = "پایان پوشش نمی‌تواند قبل از شروع پوشش باشد."
        if self.contract_id:
            contract = self.contract
            if not self.insurer_id:
                self.insurer = contract.insurer
            elif contract.insurer_id != self.insurer_id:
                errors["insurer"] = "بیمه‌گر دارایی باید با بیمه‌گر قرارداد یکسان باشد."
            if self.company_id and not contract.companies.filter(pk=self.company_id).exists():
                errors["contract"] = "قرارداد انتخاب‌شده برای شرکت این دارایی تعریف نشده است."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.asset_code} — {self.name}"


class Vehicle(models.Model):
    asset = models.OneToOneField(InsuredAsset, on_delete=models.CASCADE, related_name="vehicle_details")
    plate_number = models.CharField("شماره پلاک", max_length=40)
    vin = models.CharField("شماره شاسی/VIN", max_length=80, blank=True, db_index=True)
    engine_number = models.CharField("شماره موتور", max_length=80, blank=True)
    make = models.CharField("سازنده", max_length=100, blank=True)
    model_name = models.CharField("مدل", max_length=100, blank=True)
    model_year = models.PositiveSmallIntegerField("سال ساخت", null=True, blank=True)

    class Meta:
        verbose_name = "مشخصات خودرو"
        verbose_name_plural = "مشخصات خودروها"

    def __str__(self):
        return self.plate_number
