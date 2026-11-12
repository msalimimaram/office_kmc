from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def asset_owner_company_id(asset, *, on_date=None):
    """Resolve current employer without trusting a stale legacy company pointer."""
    if asset.company_id:
        return asset.company_id
    if not asset.person_id:
        return None
    from organizations.models import PersonEmployment
    person = asset.person.employee if asset.person.employee_id else asset.person
    today = on_date or timezone.localdate()
    history = PersonEmployment.objects.filter(person_id=person.pk)
    active = history.filter(status=PersonEmployment.Status.ACTIVE).filter(
        models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
    ).filter(
        models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
    ).order_by("-valid_from", "-pk").first()
    if active:
        return active.company_id
    return person.company_id if not history.exists() else None


def allowed_asset_lines(asset_type):
    return {
        "vehicle": {"third_party", "body", "vehicle"},
        "property": {"fire", "property", "liability"},
        "equipment": {"fire", "equipment", "liability"},
        "other": {"other"},
    }.get(asset_type, set())


class InsuredAssetQuerySet(models.QuerySet):
    PROTECTED_FIELDS = {
        "insured_value", "insurer", "insurer_id", "contract", "contract_id",
        "policy_number", "policy_start", "policy_end",
    }

    def update(self, **kwargs):
        if self.PROTECTED_FIELDS.intersection(kwargs):
            raise ValidationError(
                "ارزش و اطلاعات بیمه‌نامه فقط از مسیر گردش تأیید دارایی قابل تغییر است."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if self.PROTECTED_FIELDS.intersection(fields):
            raise ValidationError(
                "ویرایش گروهی ارزش و بیمه‌نامه خارج از گردش تأیید مجاز نیست."
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)


class ImmutableAssetApprovalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("سوابق دارایی فقط از مسیر گردش تأیید تغییر می‌کنند.")

    def delete(self):
        raise ValidationError("سوابق بیمه‌ای دارایی حذف نمی‌شوند.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی سوابق بیمه‌ای دارایی مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی سوابق تأیید دارایی مجاز نیست.")


class InsuredAsset(models.Model):
    objects = InsuredAssetQuerySet.as_manager()

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

    POLICY_SNAPSHOT_FIELDS = (
        "insured_value", "insurer_id", "contract_id",
        "policy_number", "policy_start", "policy_end",
    )

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
            # Validate the owner/contract relationship when the snapshot is
            # first created. Later employment transfers must not invalidate
            # an immutable historical policy snapshot.
            if self._state.adding:
                owner_company_id = asset_owner_company_id(self)
                if not owner_company_id:
                    errors["contract"] = "شرکت محل اشتغال معتبر برای مالک دارایی پیدا نشد؛ قرارداد قابل اتصال نیست."
                elif not contract.companies.filter(pk=owner_company_id).exists():
                    errors["contract"] = "قرارداد برای شرکت مالک/محل اشتغال فعلی دارایی تعریف نشده است."
                if contract.line not in allowed_asset_lines(self.asset_type):
                    errors["contract"] = "رشته قرارداد با نوع دارایی انتخاب‌شده سازگار نیست."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and not getattr(self, "_workflow_sync", False):
            previous = type(self).objects.filter(pk=self.pk).values(
                *self.POLICY_SNAPSHOT_FIELDS
            ).get()
            changed = [
                field for field in self.POLICY_SNAPSHOT_FIELDS
                if previous[field] != getattr(self, field)
            ]
            if changed:
                raise ValidationError(
                    "اطلاعات ارزش و بیمه‌نامه دارایی فقط از مسیر سوابق تأییدشده "
                    "ارزیابی و دوره بیمه‌نامه قابل تغییر است."
                )
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
    objects = ImmutableAssetApprovalQuerySet.as_manager()
    class Method(models.TextChoices):
        FORMAL = "formal", "ارزیابی رسمی"
        EXPERT = "expert", "نظر کارشناس"
        DECLARED = "declared", "اظهار واحد"
        LEGACY = "legacy_snapshot", "انتقال از اطلاعات قدیمی"

    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        LEGACY = "legacy", "سابقه قدیمی؛ فاقد تأیید در گردش جدید"

    asset = models.ForeignKey(InsuredAsset, on_delete=models.PROTECT, related_name="valuations")
    valuation_date = models.DateField("تاریخ ارزیابی", null=True, blank=True)
    market_value = models.DecimalField("ارزش روز", max_digits=18, decimal_places=2, default=0)
    insured_value = models.DecimalField("ارزش بیمه‌شده", max_digits=18, decimal_places=2, default=0)
    method = models.CharField("روش ارزیابی", max_length=24, choices=Method.choices, default=Method.EXPERT)
    status = models.CharField("وضعیت تأیید", max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL)
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
            update_fields = set(kwargs.get("update_fields") or ())
            if not getattr(self, "_workflow_sync", False) or not update_fields or not update_fields.issubset({"status", "approved_by"}):
                raise ValidationError("سابقه ارزیابی ویرایش نمی‌شود؛ فقط وضعیت تأیید از گردش کار قابل تغییر است.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        if step_code not in {self.Status.PENDING_APPROVAL, self.Status.APPROVED, self.Status.REJECTED}:
            return
        # A decision stage is not the commit point. Keep the valuation and the
        # asset snapshot unchanged until the authorized final-close transition.
        if step_code in {self.Status.APPROVED, self.Status.REJECTED} and not closed:
            return
        if self.status != step_code or (
            step_code == self.Status.APPROVED
            and self.approved_by_id != getattr(actor, "pk", None)
        ):
            self.status = step_code
            update_fields = ["status"]
            if step_code == self.Status.APPROVED:
                self.approved_by = actor
                update_fields.append("approved_by")
            self._workflow_sync = True
            try:
                self.save(update_fields=update_fields)
            finally:
                self._workflow_sync = False
        if step_code == self.Status.APPROVED and closed:
            asset = self.asset
            asset.insured_value = self.insured_value
            asset._workflow_sync = True
            try:
                asset.save(update_fields=["insured_value", "updated_at"])
            finally:
                asset._workflow_sync = False

    def delete(self, *args, **kwargs):
        raise ValidationError("سابقه ارزیابی حذف نمی‌شود.")

    def __str__(self):
        return f"{self.asset} — {self.valuation_date or self.created_at.date()}"


class AssetPolicyPeriod(models.Model):
    objects = ImmutableAssetApprovalQuerySet.as_manager()
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        APPROVED = "approved", "تأییدشده؛ در انتظار شروع پوشش"
        ACTIVE = "active", "فعال"
        REJECTED = "rejected", "ردشده"
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
        if self.contract_id and self._state.adding:
            contract = self.contract
            if contract.insurer_id != self.insurer_id:
                raise ValidationError({"insurer": "بیمه‌گر دوره باید با بیمه‌گر قرارداد یکسان باشد."})
            if contract.status != "active" or not contract.is_active:
                raise ValidationError({"contract": "فقط قرارداد فعال و تأییدشده برای ایجاد دوره بیمه‌نامه قابل انتخاب است."})
            if self.policy_start and self.policy_start < contract.start_date:
                raise ValidationError({"policy_start": "شروع پوشش نمی‌تواند قبل از شروع اعتبار قرارداد باشد."})
            if self.policy_end and self.policy_end > contract.end_date:
                raise ValidationError({"policy_end": "پایان پوشش نمی‌تواند بعد از پایان اعتبار قرارداد باشد."})
            if contract.line not in allowed_asset_lines(self.asset.asset_type):
                raise ValidationError({"contract": "رشته قرارداد با نوع دارایی انتخاب‌شده سازگار نیست."})
            owner_company_id = asset_owner_company_id(self.asset)
            if not owner_company_id:
                raise ValidationError({"contract": "شرکت محل اشتغال معتبر برای مالک دارایی پیدا نشد."})
            if not contract.companies.filter(pk=owner_company_id).exists():
                raise ValidationError({"contract": "قرارداد برای شرکت مالک/محل اشتغال فعلی دارایی تعریف نشده است."})

    def save(self, *args, **kwargs):
        if self.pk:
            update_fields = set(kwargs.get("update_fields") or ())
            if not getattr(self, "_workflow_sync", False) or not update_fields or not update_fields.issubset({"status", "approved_by"}):
                raise ValidationError("دوره بیمه‌نامه پس از ثبت فقط از مسیر گردش تأیید تغییر می‌کند.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        # Approval/rejection must not activate a period or change the asset
        # snapshot until the workflow has been finally closed.
        if step_code in {"approved", self.Status.REJECTED} and not closed:
            return
        if step_code == "approved" and closed:
            from django.utils import timezone

            today = timezone.localdate()
            if self.contract_id and self.contract.status == "terminated":
                target = self.Status.TERMINATED
            elif self.contract_id and self.contract.status == "expired":
                target = self.Status.EXPIRED
            elif self.policy_end and self.policy_end < today:
                target = self.Status.EXPIRED
            elif self.policy_start and self.policy_start > today:
                target = self.Status.APPROVED
            elif self.contract_id and (
                self.contract.status != "active" or not self.contract.is_active
            ):
                target = self.Status.APPROVED
            else:
                target = self.Status.ACTIVE
            self.status = target
            self.approved_by = actor
            self._workflow_sync = True
            try:
                self.save(update_fields=["status", "approved_by"])
            finally:
                self._workflow_sync = False
            if self.status == self.Status.ACTIVE:
                self._apply_to_asset_snapshot(on_date=today)
            return
        if step_code == self.Status.PENDING_APPROVAL:
            if self.status != step_code:
                self.status = step_code
                self._workflow_sync = True
                try:
                    self.save(update_fields=["status"])
                finally:
                    self._workflow_sync = False
        elif step_code == self.Status.REJECTED and closed:
            if self.status != step_code:
                self.status = step_code
                self._workflow_sync = True
                try:
                    self.save(update_fields=["status"])
                finally:
                    self._workflow_sync = False

    def _apply_to_asset_snapshot(self, *, on_date=None):
        # The legacy snapshot stores one policy only. Preserve a different
        # policy while its recorded coverage is still current, but permit a
        # due replacement to take over after the old snapshot expires.
        # Honour the caller's effective processing date so backfills and
        # deterministic lifecycle runs behave exactly like the daily command.
        today = on_date or timezone.localdate()
        if (
            not self.contract_id
            or self.status != self.Status.ACTIVE
            or (self.policy_start and self.policy_start > today)
            or (self.policy_end and self.policy_end < today)
            or self.contract.status != "active"
            or not self.contract.is_active
        ):
            return False
        asset = self.asset
        if (
            asset.contract_id
            and asset.contract_id != self.contract_id
            and asset.is_active
            and (asset.policy_end is None or asset.policy_end >= today)
        ):
            return False
        asset.insurer = self.insurer
        asset.contract = self.contract
        asset.policy_number = self.policy_number
        asset.policy_start = self.policy_start
        asset.policy_end = self.policy_end
        asset.is_active = True
        asset._workflow_sync = True
        try:
            asset.save(update_fields=[
                "insurer", "contract", "policy_number", "policy_start",
                "policy_end", "is_active", "updated_at",
            ])
        finally:
            asset._workflow_sync = False

    @transaction.atomic
    def expire_if_due(self, *, on_date=None):
        """Expire an active policy after its final covered calendar day."""
        today = on_date or timezone.localdate()
        period = type(self).objects.select_for_update().get(pk=self.pk)
        if period.status != self.Status.ACTIVE:
            self.status = period.status
            return False
        if period.contract_id and period.contract.status == "terminated":
            period.status = self.Status.TERMINATED
        elif period.contract_id and period.contract.status == "expired":
            period.status = self.Status.EXPIRED
        elif not period.policy_end or period.policy_end >= today:
            self.status = period.status
            return False
        else:
            period.status = self.Status.EXPIRED
        period._workflow_sync = True
        try:
            period.save(update_fields=["status"])
        finally:
            period._workflow_sync = False
        self.status = period.status
        return True

    @transaction.atomic
    def activate_if_due(self, *, on_date=None):
        today = on_date or timezone.localdate()
        period = type(self).objects.select_for_update().select_related(
            "asset", "insurer", "contract"
        ).get(pk=self.pk)
        if period.status != self.Status.APPROVED:
            self.status = period.status
            return False
        if period.policy_start and period.policy_start > today:
            self.status = period.status
            return False
        if period.contract_id:
            if period.contract.status == "terminated":
                period.status = self.Status.TERMINATED
            elif period.contract.status == "expired":
                period.status = self.Status.EXPIRED
            elif period.contract.status != "active" or not period.contract.is_active:
                self.status = period.status
                return False
        if period.status not in {self.Status.TERMINATED, self.Status.EXPIRED}:
            if period.policy_end and period.policy_end < today:
                period.status = self.Status.EXPIRED
            else:
                period.status = self.Status.ACTIVE
        period._workflow_sync = True
        try:
            period.save(update_fields=["status"])
        finally:
            period._workflow_sync = False
        self.status = period.status
        if period.status == self.Status.ACTIVE:
            period._apply_to_asset_snapshot(on_date=today)
        return True

    def delete(self, *args, **kwargs):
        raise ValidationError("دوره‌های بیمه‌نامه به‌صورت سابقه‌ای حفظ می‌شوند و حذف نمی‌شوند.")

    def __str__(self):
        return f"{self.policy_number} — {self.asset}"


class AssetPolicyEndorsement(models.Model):
    objects = ImmutableAssetApprovalQuerySet.as_manager()
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        LEGACY = "legacy", "سابقه قدیمی؛ فاقد تأیید در گردش جدید"

    policy_period = models.ForeignKey(AssetPolicyPeriod, on_delete=models.PROTECT, related_name="endorsements")
    endorsement_number = models.CharField("شماره الحاقیه", max_length=100)
    effective_date = models.DateField("تاریخ اثر", null=True, blank=True)
    description = models.TextField("شرح تغییر")
    document = models.FileField("فایل الحاقیه", upload_to="asset_endorsements/")
    status = models.CharField("وضعیت تأیید", max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL)
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

    def save(self, *args, **kwargs):
        if self.pk:
            update_fields = set(kwargs.get("update_fields") or ())
            if not getattr(self, "_workflow_sync", False) or not update_fields or not update_fields.issubset({"status", "approved_by"}):
                raise ValidationError("الحاقیه پس از ثبت قابل ویرایش نیست؛ فقط وضعیت تأیید از گردش کار قابل تغییر است.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        if step_code not in {self.Status.PENDING_APPROVAL, self.Status.APPROVED, self.Status.REJECTED}:
            return
        # Persist the approval/rejection decision only at final workflow close.
        if step_code in {self.Status.APPROVED, self.Status.REJECTED} and not closed:
            return
        if self.status == step_code and (
            step_code != self.Status.APPROVED
            or self.approved_by_id == getattr(actor, "pk", None)
        ):
            return
        self.status = step_code
        update_fields = ["status"]
        if step_code == self.Status.APPROVED:
            self.approved_by = actor
            update_fields.append("approved_by")
        self._workflow_sync = True
        try:
            self.save(update_fields=update_fields)
        finally:
            self._workflow_sync = False

    def delete(self, *args, **kwargs):
        raise ValidationError("الحاقیه‌های بیمه‌نامه حذف نمی‌شوند.")

