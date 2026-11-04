from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils import timezone


class ImmutableAuditQuerySet(models.QuerySet):
    """Prevent application-level mutation of persisted audit events."""

    def update(self, **kwargs):
        raise ValidationError("رویداد ممیزی قابل ویرایش نیست؛ رویداد اصلاحی جدید ثبت کنید.")

    def delete(self):
        raise PermissionDenied("حذف رویداد ممیزی مجاز نیست.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی رویداد ممیزی مجاز نیست.")


class AuditEvent(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    action = models.CharField("عملیات", max_length=120)
    object_type = models.CharField("نوع رکورد", max_length=120, blank=True)
    object_id = models.CharField("شناسه رکورد", max_length=100, blank=True)
    summary = models.TextField("شرح", blank=True)
    before_data = models.JSONField("داده قبل از تغییر", default=dict, blank=True)
    after_data = models.JSONField("داده بعد از تغییر", default=dict, blank=True)
    metadata = models.JSONField("اطلاعات تکمیلی", default=dict, blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("مرورگر/عامل کاربر", max_length=512, blank=True)
    correlation_id = models.UUIDField("شناسه همبستگی", null=True, blank=True, db_index=True)
    created_at = models.DateTimeField("زمان رخداد", default=timezone.now, editable=False, db_index=True)

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "رویداد ممیزی"
        verbose_name_plural = "رویدادهای ممیزی"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد ممیزی قابل ویرایش نیست؛ رویداد اصلاحی جدید ثبت کنید.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("حذف رویداد ممیزی مجاز نیست.")

    def __str__(self):
        return f"{self.action} — {self.created_at:%Y-%m-%d %H:%M:%S}"
