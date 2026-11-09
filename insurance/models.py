from datetime import date

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Insurer(models.Model):
    name = models.CharField("نام بیمه‌گر", max_length=200, unique=True)
    contact_name = models.CharField("شخص تماس", max_length=150, blank=True)
    contact_email = models.EmailField("ایمیل", blank=True)
    contact_phone = models.CharField("تلفن", max_length=40, blank=True)
    is_active = models.BooleanField("فعال", default=True)

    def __str__(self):
        return self.name


class InsuranceLine(models.TextChoices):
    HEALTH = "health", "درمان تکمیلی"
    LIFE = "life", "عمر و حوادث"
    LIABILITY = "liability", "مسئولیت"
    FIRE = "fire", "آتش‌سوزی و اموال"
    THIRD_PARTY = "third_party", "شخص ثالث"
    BODY = "body", "بدنه خودرو"
    OTHER = "other", "سایر"


class Contract(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        APPROVED = "approved", "تأییدشده؛ در انتظار تاریخ اثر"
        ACTIVE = "active", "فعال"
        EXPIRED = "expired", "منقضی"
        TERMINATED = "terminated", "فسخ‌شده"
        REJECTED = "rejected", "ردشده"
        LEGACY_INACTIVE = "legacy_inactive", "غیرفعال قدیمی"

    code = models.CharField("شماره قرارداد", max_length=80, unique=True)
    title = models.CharField("عنوان قرارداد", max_length=250)
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="contracts")
    line = models.CharField("رشته بیمه", max_length=30, choices=InsuranceLine.choices)
    start_date = models.DateField("شروع قرارداد")
    end_date = models.DateField("پایان قرارداد")
    companies = models.ManyToManyField("organizations.Company", related_name="insurance_contracts", blank=True)
    coverage_summary = models.TextField("خلاصه پوشش‌ها", blank=True)
    terms = models.TextField("شرایط و استثناها", blank=True)
    status = models.CharField("وضعیت چرخه عمر", max_length=24, choices=Status.choices, default=Status.DRAFT)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="contract_end_on_or_after_start",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "تاریخ پایان قرارداد نمی‌تواند قبل از تاریخ شروع باشد."})

    def save(self, *args, **kwargs):
        # Preserve compatibility for existing callers that explicitly create
        # active contracts; the operational form sets DRAFT + is_active=False.
        if self.status == self.Status.DRAFT and self.is_active:
            self.status = self.Status.ACTIVE
        self.is_active = self.status == self.Status.ACTIVE
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} — {self.title}"


class ImmutableContractRevisionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("نسخه‌های قرارداد از طریق update گروهی قابل تغییر نیستند.")

    def delete(self):
        raise ValidationError("حذف نسخه‌های قرارداد مجاز نیست.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی نسخه‌های قرارداد مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی نسخه‌های قرارداد مجاز نیست.")


class ContractRevision(models.Model):
    objects = ImmutableContractRevisionQuerySet.as_manager()

    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"
        TERMINATED = "terminated", "فسخ تأییدشده"
        LEGACY = "legacy", "نسخه قدیمی؛ فاقد گردش تأیید جدید"

    contract = models.ForeignKey(Contract, on_delete=models.PROTECT, related_name="revisions")
    revision_number = models.PositiveIntegerField("شماره نسخه")
    description = models.TextField("شرح تغییر")
    document = models.FileField("فایل سند غیرپزشکی", upload_to="contract_docs/", blank=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField("وضعیت نسخه", max_length=24, choices=Status.choices, default=Status.PENDING_APPROVAL)
    snapshot = models.JSONField("تصویر کامل شرایط نسخه", default=dict, blank=True)
    effective_date = models.DateField("تاریخ اثر", null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_contract_revisions",
    )
    approved_at = models.DateTimeField("زمان تأیید", null=True, blank=True)
    applied_at = models.DateTimeField("زمان اعمال نسخه", null=True, blank=True)
    is_termination = models.BooleanField("درخواست فسخ", default=False)
    termination_reason = models.TextField("علت فسخ", blank=True)
    notice_date = models.DateField("تاریخ اعلام فسخ", null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["contract", "revision_number"], name="uniq_contract_revision"),
            models.UniqueConstraint(
                fields=["contract"],
                condition=models.Q(status="pending_approval"),
                name="uniq_pending_contract_revision",
            ),
        ]
        ordering = ["-revision_number", "-pk"]

    def clean(self):
        super().clean()
        if self.revision_number < 1:
            raise ValidationError({"revision_number": "شماره نسخه باید مثبت باشد."})
        if not isinstance(self.snapshot, dict):
            raise ValidationError({"snapshot": "تصویر نسخه باید ساختار JSON شیء داشته باشد."})
        if self.is_termination and not self.termination_reason.strip():
            raise ValidationError({"termination_reason": "ثبت علت فسخ الزامی است."})
        if self.is_termination and not self.effective_date:
            raise ValidationError({"effective_date": "تاریخ اثر فسخ الزامی است."})
        if self.is_termination and self.effective_date and self.contract_id:
            if self.effective_date < self.contract.start_date:
                raise ValidationError({"effective_date": "تاریخ اثر فسخ نمی‌تواند قبل از شروع قرارداد باشد."})
            if self.effective_date > self.contract.end_date:
                raise ValidationError({"effective_date": "تاریخ اثر فسخ نمی‌تواند بعد از پایان قرارداد باشد."})
            if self.notice_date and self.notice_date > self.effective_date:
                raise ValidationError({"notice_date": "تاریخ اعلام فسخ نمی‌تواند بعد از تاریخ اثرگذاری باشد."})

        if (
            self.status == self.Status.PENDING_APPROVAL
            and self.contract_id
            and type(self).objects.filter(
                contract_id=self.contract_id,
                status=self.Status.PENDING_APPROVAL,
            ).exclude(pk=self.pk).exists()
        ):
            raise ValidationError("برای هر قرارداد فقط یک نسخه در انتظار تأیید مجاز است.")

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            allowed = {"applied_at"}
            if getattr(self, "_workflow_status_update", False):
                allowed.update({"status", "approved_by", "approved_at"})
            changed = [
                field.name for field in self._meta.concrete_fields
                if field.name not in {"id", *allowed}
                and getattr(previous, field.attname) != getattr(self, field.attname)
            ]
            if changed:
                raise ValidationError(
                    "محتوای نسخه قرارداد پس از ثبت قابل ویرایش نیست؛ نسخه جدید ثبت کنید."
                )
        self.full_clean()
        return super().save(*args, **kwargs)

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        if step_code not in dict(self.Status.choices):
            return
        terminal_decisions = {self.Status.APPROVED, self.Status.REJECTED, self.Status.TERMINATED}
        # Approval/rejection/termination is not committed until the workflow case
        # itself is closed by the authorized final approver.
        if step_code in terminal_decisions and not closed:
            return

        self.status = step_code
        update_fields = ["status"]
        if step_code in {self.Status.APPROVED, self.Status.TERMINATED}:
            self.approved_by = actor
            self.approved_at = timezone.now()
            update_fields.extend(["approved_by", "approved_at"])
        self._workflow_status_update = True
        try:
            self.save(update_fields=update_fields)
        finally:
            del self._workflow_status_update

        if step_code in {self.Status.APPROVED, self.Status.TERMINATED}:
            today = timezone.localdate()
            if self.effective_date and self.effective_date <= today:
                self.apply_to_contract()
            elif self.revision_number == 1 and not self.is_termination:
                self.contract.status = Contract.Status.APPROVED
                self.contract.is_active = False
                self.contract.save(update_fields=["status", "is_active"])

    def apply_to_contract(self):
        snapshot = self.snapshot or {}
        contract = self.contract
        date_fields = {"start_date", "end_date"}
        allowed_fields = {
            "code", "title", "insurer_id", "line", "start_date", "end_date",
            "coverage_summary", "terms",
        }
        for field in allowed_fields:
            if field not in snapshot:
                continue
            value = snapshot[field]
            if field in date_fields and value:
                value = date.fromisoformat(value)
            setattr(contract, field, value)

        if self.is_termination:
            if self.effective_date and self.effective_date < contract.end_date:
                contract.end_date = self.effective_date
            contract.status = Contract.Status.TERMINATED
        else:
            today = timezone.localdate()
            if contract.end_date < today:
                contract.status = Contract.Status.EXPIRED
            elif contract.start_date > today:
                contract.status = Contract.Status.APPROVED
            else:
                contract.status = Contract.Status.ACTIVE
        contract.is_active = contract.status == Contract.Status.ACTIVE
        contract.save()
        if "company_ids" in snapshot:
            contract.companies.set(snapshot["company_ids"])
        self.applied_at = timezone.now()
        self.save(update_fields=["applied_at"])

    def delete(self, *args, **kwargs):
        raise ValidationError("حذف نسخه‌های قرارداد مجاز نیست؛ نسخه جدید ثبت کنید.")

    def __str__(self):
        return f"{self.contract.code} · نسخه {self.revision_number}"
