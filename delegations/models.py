from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.models import RoleAssignment


DELEGATABLE_ROLES = (
    (RoleAssignment.Role.INSURANCE_SPECIALIST, "کارشناس اداره بیمه"),
    (RoleAssignment.Role.SUBSIDIARY_REP, "نماینده شرکت"),
    (RoleAssignment.Role.INSURER_REP, "نماینده بیمه‌گر"),
)


class WorkDelegation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "فعال"
        SUSPENDED = "suspended", "معلق"
        REVOKED = "revoked", "لغوشده"
        EXPIRED = "expired", "منقضی"

    workflow_code = models.CharField("کد گردش‌کار", max_length=64, db_index=True)
    item_type = models.CharField(
        "زیرنوع کار", max_length=40, blank=True,
        help_text="خالی یعنی تمام زیرنوع‌های این گردش‌کار؛ برای person_change مانند iban یا mobile",
    )
    delegate_role = models.CharField("نقش پایه گیرنده", max_length=32, choices=DELEGATABLE_ROLES)
    delegate_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="received_work_delegations", verbose_name="گیرنده تفویض",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="issued_work_delegations", verbose_name="تفویض‌کننده",
    )
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="work_delegations", verbose_name="شرکت محدودکننده",
    )
    insurer = models.ForeignKey(
        "insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT,
        related_name="work_delegations", verbose_name="بیمه‌گر محدودکننده",
    )
    line_code = models.CharField("رشته بیمه‌ای", max_length=32, blank=True)
    reason = models.TextField("دلیل و محدوده اختیار", max_length=2000)
    status = models.CharField("وضعیت", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    valid_from = models.DateField("شروع اعتبار", default=timezone.localdate)
    valid_until = models.DateField("پایان اعتبار", null=True, blank=True)
    revoked_at = models.DateTimeField("زمان لغو", null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="revoked_work_delegations",
    )
    revocation_reason = models.CharField("دلیل لغو/تعلیق", max_length=1000, blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("workflow_code", "status", "valid_from", "valid_until"), name="delegation_lookup"),
            models.Index(fields=("delegate_to", "status", "valid_until"), name="delegation_inbox"),
        ]
        verbose_name = "تفویض اختیار کاری"
        verbose_name_plural = "تفویض‌های اختیار"

    def clean(self):
        super().clean()
        errors = {}
        if self.granted_by_id and self.delegate_to_id == self.granted_by_id:
            errors["delegate_to"] = "تفویض اختیار به خود مجاز نیست."
        if self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = "پایان اعتبار نمی‌تواند پیش از شروع اعتبار باشد."
        if self.delegate_role == RoleAssignment.Role.INSURANCE_SPECIALIST and not self.line_code:
            errors["line_code"] = "برای تفویض به کارشناس، رشته بیمه‌ای مشخص الزامی است."
        if self.delegate_role == RoleAssignment.Role.SUBSIDIARY_REP and not self.company_id:
            errors["company"] = "برای تفویض به نماینده شرکت، شرکت باید مشخص باشد."
        if self.delegate_role == RoleAssignment.Role.INSURER_REP and not self.insurer_id:
            errors["insurer"] = "برای تفویض به نماینده بیمه‌گر، بیمه‌گر باید مشخص باشد."
        if not (self.reason or "").strip():
            errors["reason"] = "ثبت دلیل تفویض اختیار الزامی است."
        if errors:
            raise ValidationError(errors)

    @property
    def is_effective(self):
        today = timezone.localdate()
        return (
            self.status == self.Status.ACTIVE
            and self.valid_from <= today
            and (self.valid_until is None or self.valid_until >= today)
        )

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable = {
                "workflow_code", "item_type", "delegate_role", "delegate_to_id",
                "granted_by_id", "company_id", "insurer_id", "line_code",
                "reason", "valid_from", "valid_until",
            }
            changed = [
                name for name in immutable
                if getattr(previous, name) != getattr(self, name)
            ]
            if changed:
                raise ValidationError(
                    "محدوده تفویض ثبت‌شده قابل بازنویسی نیست؛ تفویض قبلی را لغو و تفویض جدید ثبت کنید."
                )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("تفویض اختیار حذف نمی‌شود؛ آن را لغو کنید.")

    def __str__(self):
        subtype = f" / {self.item_type}" if self.item_type else ""
        return f"{self.workflow_code}{subtype} → {self.delegate_to}"


class ImmutableDelegationEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("تاریخچه تفویض اختیار قابل ویرایش نیست.")

    def delete(self):
        raise ValidationError("تاریخچه تفویض اختیار قابل حذف نیست.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی تاریخچه تفویض مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی تاریخچه تفویض مجاز نیست.")


class DelegationEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "ایجاد تفویض"
        CASE_ROUTED = "case_routed", "ارجاع پرونده"
        CASE_RETURNED = "case_returned", "بازگشت پرونده"
        SUSPENDED = "suspended", "تعلیق"
        RESUMED = "resumed", "فعال‌سازی مجدد"
        REVOKED = "revoked", "لغو"
        EXPIRED = "expired", "انقضا"

    objects = ImmutableDelegationEventQuerySet.as_manager()

    delegation = models.ForeignKey(
        WorkDelegation, on_delete=models.PROTECT, related_name="events",
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=24, choices=EventType.choices)
    summary = models.CharField(max_length=1000)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "رویداد تفویض اختیار"
        verbose_name_plural = "تاریخچه تفویض اختیار"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد تفویض قابل ویرایش نیست.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویداد تفویض قابل حذف نیست.")
