from django.db import models
from django.conf import settings

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
