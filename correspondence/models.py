from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CorrespondenceSequence(models.Model):
    """Daily shared serial for inbound and outbound correspondence."""

    solar_date = models.CharField("تاریخ شمسی فشرده", max_length=8, unique=True)
    last_number = models.PositiveIntegerField("آخرین شماره صادرشده", default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-solar_date",)
        verbose_name = "شمارنده شماره مکاتبات"
        verbose_name_plural = "شمارنده‌های شماره مکاتبات"

    def __str__(self):
        return f"{self.solar_date} — {self.last_number}"


class Correspondence(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "ایمیل"
        PHONE = "phone", "تلفن"
        MEETING = "meeting", "جلسه"
        LETTER = "letter", "نامه"
        PORTAL = "portal", "سامانه"
        OTHER = "other", "سایر"

    class Direction(models.TextChoices):
        INBOUND = "inbound", "دریافتی"
        OUTBOUND = "outbound", "ارسالی"
        INTERNAL = "internal", "داخلی"

    class FollowUp(models.TextChoices):
        PENDING = "pending", "در انتظار پیگیری"
        COMPLETED = "completed", "پیگیری‌شده"
        NOT_REQUIRED = "not_required", "نیازمند پیگیری نیست"

    internal_number = models.CharField("شماره داخلی", max_length=20, unique=True, blank=True, default="")
    subject = models.CharField("موضوع", max_length=250)
    channel = models.CharField("روش ارتباط", max_length=20, choices=Channel.choices)
    direction = models.CharField("جهت مکاتبه", max_length=20, choices=Direction.choices)
    company = models.ForeignKey("organizations.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    insurer = models.ForeignKey("insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    external_reference = models.CharField("شماره نامه/مرجع بیرونی", max_length=120, blank=True)
    summary = models.TextField("خلاصه و اقدام انجام‌شده")
    occurred_at = models.DateTimeField("زمان ارتباط", default=timezone.now)
    follow_up_due = models.DateField("مهلت پیگیری", null=True, blank=True)
    follow_up_status = models.CharField("وضعیت پیگیری", max_length=20, choices=FollowUp.choices, default=FollowUp.PENDING)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_correspondence")
    is_confidential = models.BooleanField("محرمانه", default=False)
    attachment = models.FileField("پیوست", upload_to="correspondence/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_correspondence")
    created_at = models.DateTimeField("ثبت در سامانه", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        ordering = ["follow_up_status", "follow_up_due", "-occurred_at"]
        verbose_name = "مکاتبه"
        verbose_name_plural = "مکاتبات و پیگیری‌ها"

    def clean(self):
        super().clean()
        errors = {}
        if self.contract_id and self.insurer_id and self.contract.insurer_id != self.insurer_id:
            errors["insurer"] = "بیمه‌گر مکاتبه باید با بیمه‌گر قرارداد یکسان باشد."
        if self.contract_id and self.company_id and not self.contract.companies.filter(pk=self.company_id).exists():
            errors["contract"] = "قرارداد برای شرکت انتخاب‌شده تعریف نشده است."
        if not self.internal_number:
            errors["internal_number"] = "شماره داخلی باید از شمارنده مرکزی صادر شود."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.internal_number} — {self.subject}"


class CorrespondenceLink(models.Model):
    correspondence = models.ForeignKey(Correspondence, on_delete=models.PROTECT, related_name="links")
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("correspondence", "content_type", "object_id"), name="uniq_correspondence_link"),
        ]
        indexes = [models.Index(fields=("content_type", "object_id"), name="correspondence_link_target")]
        verbose_name = "ارتباط مکاتبه"
        verbose_name_plural = "ارتباط‌های مکاتبه"


class CorrespondenceEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "ثبت مکاتبه"
        REFERRED = "referred", "ارجاع"
        FOLLOW_UP = "follow_up", "پیگیری"
        RESPONSE = "response", "دریافت پاسخ"
        STATUS_CHANGED = "status_changed", "تغییر وضعیت"
        ARCHIVED = "archived", "بایگانی"

    correspondence = models.ForeignKey(Correspondence, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    summary = models.TextField("شرح اقدام", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("occurred_at", "pk")
        verbose_name = "رویداد مکاتبه"
        verbose_name_plural = "رویدادهای مکاتبه"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد مکاتبه ویرایش نمی‌شود؛ رویداد جدید ثبت کنید.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویداد مکاتبه حذف نمی‌شود.")
