from django.conf import settings
from django.db import models
from django.utils import timezone


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

    subject = models.CharField("موضوع", max_length=250)
    channel = models.CharField("روش ارتباط", max_length=20, choices=Channel.choices)
    direction = models.CharField("جهت مکاتبه", max_length=20, choices=Direction.choices)
    company = models.ForeignKey("organizations.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    insurer = models.ForeignKey("insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    contract = models.ForeignKey("insurance.Contract", null=True, blank=True, on_delete=models.PROTECT, related_name="correspondence")
    external_reference = models.CharField("شماره نامه/مرجع", max_length=120, blank=True)
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

    def __str__(self):
        return self.subject
