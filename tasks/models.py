from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class InternalTask(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "کم"
        NORMAL = "normal", "عادی"
        HIGH = "high", "زیاد"
        URGENT = "urgent", "فوری"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        IN_PROGRESS = "in_progress", "در حال انجام"
        WAITING = "waiting", "در انتظار"
        DONE = "done", "انجام‌شده"
        CANCELLED = "cancelled", "لغوشده"

    title = models.CharField("عنوان", max_length=250)
    description = models.TextField("شرح")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_tasks")
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="internal_tasks")
    priority = models.CharField("اولویت", max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField("وضعیت", max_length=16, choices=Status.choices, default=Status.OPEN)
    due_at = models.DateTimeField("مهلت انجام", null=True, blank=True)
    related_request = models.ForeignKey("requests_portal.ServiceRequest", null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_at", "-created_at"]
        verbose_name = "وظیفه"
        verbose_name_plural = "وظایف داخلی"

    def __str__(self):
        return self.title


class TaskEvent(models.Model):
    class EventType(models.TextChoices):
        CREATED = "created", "ایجاد"
        ASSIGNED = "assigned", "تخصیص"
        STATUS = "status", "تغییر وضعیت"
        COMMENT = "comment", "یادداشت"
        DUE_CHANGED = "due_changed", "تغییر مهلت"
        FIRST_VIEWED = "first_viewed", "اولین مشاهده"
        FIRST_ACTION = "first_action", "اولین اقدام"

    task = models.ForeignKey(InternalTask, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    from_value = models.CharField(max_length=80, blank=True)
    to_value = models.CharField(max_length=80, blank=True)
    note = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("occurred_at", "pk")
        verbose_name = "رویداد وظیفه"
        verbose_name_plural = "تاریخچه وظایف"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد وظیفه قابل ویرایش نیست؛ رویداد جدید ثبت کنید.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویداد وظیفه قابل حذف نیست.")
