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
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="insured_assets",
    )
    person = models.ForeignKey(
        "organizations.Person", null=True, blank=True, on_delete=models.PROTECT,
        related_name="insured_assets",
        help_text="برای دارایی شخصی؛ برای دارایی شرکتی خالی باشد.",
    )
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
                condition=(
                    models.Q(company__isnull=False, person__isnull=True)
                    | models.Q(company__isnull=True, person__isnull=False)
                ),
                name="insured_asset_single_owner",
            ),
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
        if bool(self.company_id) == bool(self.person_id):
            errors["company"] = "دارایی باید دقیقاً یک مالک داشته باشد: شرکت یا شخص."
        if self.contract_id:
            contract = self.contract
            if not self.insurer_id:
                self.insurer = contract.insurer
            elif contract.insurer_id != self.insurer_id:
                errors["insurer"] = "بیمه‌گر دارایی باید با بیمه‌گر قرارداد یکسان باشد."
            if self.company_id and not contract.companies.filter(pk=self.company_id).exists():
                errors["contract"] = "قرارداد انتخاب‌شده برای شرکت این دارایی تعریف نشده است."
            if self.person_id and self.person.company_id and not contract.companies.filter(pk=self.person.company_id).exists():
                errors["contract"] = "قرارداد انتخاب‌شده برای شرکت محل اشتغال شخص تعریف نشده است."
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

    def clean(self):
        super().clean()
        if self.asset_id and self.asset.asset_type != InsuredAsset.Type.VEHICLE:
            raise ValidationError({"asset": "مشخصات خودرو فقط به دارایی از نوع خودرو متصل می‌شود."})
        if not self.plate_number.strip():
            raise ValidationError({"plate_number": "شماره پلاک الزامی است."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.plate_number


class AssetValuation(models.Model):
    class Method(models.TextChoices):
        FORMAL = "formal", "ارزیابی رسمی"
        EXPERT = "expert", "نظر کارشناس"
        DECLARED = "declared", "اظهار واحد"
        LEGACY = "legacy_snapshot", "انتقال از اطلاعات قدیمی"

    asset = models.ForeignKey(InsuredAsset, on_delete=models.PROTECT, related_name="valuations")
    valuation_date = models.DateField("تاریخ ارزیابی", null=True, blank=True)
    market_value = models.DecimalField("ارزش روز", max_digits=18, decimal_places=2, default=0)
    insured_value = models.DecimalField("ارزش بیمه‌شده", max_digits=18, decimal_places=2, default=0)
    method = models.CharField("روش ارزیابی", max_length=24, choices=Method.choices, default=Method.EXPERT)
    source_reference = models.CharField("مرجع ارزیابی", max_length=160, blank=True)
    note = models.TextField("توضیحات", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="asset_valuations")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="approved_asset_valuations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("asset_id", "-valuation_date", "-created_at")
        constraints = [
            models.CheckConstraint(condition=models.Q(market_value__gte=0), name="asset_market_value_nonnegative"),
            models.CheckConstraint(condition=models.Q(insured_value__gte=0), name="asset_valuation_insured_nonnegative"),
        ]
        verbose_name = "ارزیابی دارایی"
        verbose_name_plural = "سوابق ارزیابی دارایی"

    def clean(self):
        super().clean()
        if self.market_value < 0 or self.insured_value < 0:
            raise ValidationError("مبالغ ارزیابی نمی‌توانند منفی باشند.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("سابقه ارزیابی ویرایش نمی‌شود؛ ارزیابی جدید ثبت کنید.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("سابقه ارزیابی حذف نمی‌شود.")

    def __str__(self):
        return f"{self.asset} — {self.valuation_date or self.created_at.date()}"


class AssetPolicyPeriod(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        ACTIVE = "active", "فعال"
        EXPIRED = "expired", "منقضی"
        TERMINATED = "terminated", "فسخ‌شده"
        SUPERSEDED = "superseded", "جایگزین‌شده"

    asset = models.ForeignKey(InsuredAsset, on_delete=models.PROTECT, related_name="policy_periods")
    insurer = models.ForeignKey("insurance.Insurer", on_delete=models.PROTECT, related_name="asset_policy_periods")
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="asset_policy_periods")
    policy_number = models.CharField("شماره بیمه‌نامه", max_length=100)
    policy_start = models.DateField("شروع پوشش", null=True, blank=True)
    policy_end = models.DateField("پایان پوشش", null=True, blank=True)
    status = models.CharField("وضعیت", max_length=16, choices=Status.choices, default=Status.DRAFT)
    source_reference = models.CharField("مرجع منبع", max_length=160, blank=True)
    note = models.TextField("توضیحات", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="asset_policy_periods_created")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="asset_policy_periods_approved",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("asset_id", "-policy_start", "-created_at")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(policy_end__isnull=True) | models.Q(policy_start__isnull=True) | models.Q(policy_end__gte=models.F("policy_start")),
                name="asset_policy_period_dates",
            ),
        ]
        verbose_name = "دوره بیمه‌نامه دارایی"
        verbose_name_plural = "دوره‌های بیمه‌نامه دارایی"

    def clean(self):
        super().clean()
        if self.policy_start and self.policy_end and self.policy_end < self.policy_start:
            raise ValidationError({"policy_end": "پایان پوشش نمی‌تواند قبل از شروع باشد."})
        if self.contract_id and self.contract.insurer_id != self.insurer_id:
            raise ValidationError({"insurer": "بیمه‌گر دوره باید با بیمه‌گر قرارداد یکسان باشد."})
        if self.contract_id and self.asset.company_id and not self.contract.companies.filter(pk=self.asset.company_id).exists():
            raise ValidationError({"contract": "قرارداد برای شرکت مالک این دارایی تعریف نشده است."})
        if self.contract_id and self.asset.person_id and self.asset.person.company_id and not self.contract.companies.filter(pk=self.asset.person.company_id).exists():
            raise ValidationError({"contract": "قرارداد برای شرکت محل اشتغال مالک شخصی تعریف نشده است."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.policy_number} — {self.asset}"


class AssetPolicyEndorsement(models.Model):
    policy_period = models.ForeignKey(AssetPolicyPeriod, on_delete=models.PROTECT, related_name="endorsements")
    endorsement_number = models.CharField("شماره الحاقیه", max_length=100)
    effective_date = models.DateField("تاریخ اثر", null=True, blank=True)
    description = models.TextField("شرح تغییر")
    document = models.FileField("فایل الحاقیه", upload_to="asset_endorsements/")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="approved_asset_endorsements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("policy_period", "endorsement_number"), name="uniq_asset_policy_endorsement"),
        ]
        verbose_name = "الحاقیه بیمه‌نامه دارایی"
        verbose_name_plural = "الحاقیه‌های بیمه‌نامه دارایی"
