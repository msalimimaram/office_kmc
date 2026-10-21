from django.conf import settings
from django.db import models
from django.utils import timezone


class Announcement(models.Model):
    class Audience(models.TextChoices):
        ALL = "all", "همه کاربران"
        STAFF = "staff", "اداره بیمه"
        SUBSIDIARY = "subsidiary", "نمایندگان شرکت‌ها"
        EMPLOYEES = "employees", "کارکنان و بیمه‌شدگان"
        INSURERS = "insurers", "شرکت‌های بیمه‌گر"
        FINANCE_LEGAL = "finance_legal", "مالی و حقوقی"

    title = models.CharField("عنوان", max_length=250)
    body = models.TextField("متن اطلاعیه")
    audience = models.CharField("مخاطب", max_length=20, choices=Audience.choices, default=Audience.ALL)
    company = models.ForeignKey("organizations.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="announcements")
    attachment = models.FileField("پیوست", upload_to="announcement_files/", blank=True)
    is_published = models.BooleanField("منتشر شده", default=False)
    publish_at = models.DateTimeField("زمان انتشار", default=timezone.now)
    expires_at = models.DateTimeField("پایان اعتبار", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="announcements")
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        ordering = ["-publish_at", "-created_at"]
        verbose_name = "اطلاعیه"
        verbose_name_plural = "اطلاعیه‌ها و بخشنامه‌ها"

    def __str__(self):
        return self.title

    @property
    def is_current(self):
        now = timezone.now()
        return self.is_published and self.publish_at <= now and (self.expires_at is None or self.expires_at >= now)
