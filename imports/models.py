from django.db import models
from django.conf import settings

class ImportBatch(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "بارگذاری‌شده"
        VALIDATED = "validated", "اعتبارسنجی‌شده"
        PROCESSED = "processed", "پردازش‌شده"
        FAILED = "failed", "ناموفق"
    batch_number = models.CharField("شماره عملیات", max_length=40, unique=True)
    source_type = models.CharField("نوع داده", max_length=50, default="claims")
    file = models.FileField("فایل اکسل", upload_to="imports/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    status = models.CharField("وضعیت", max_length=16, choices=Status.choices, default=Status.UPLOADED)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)
    result_report = models.TextField("گزارش نتیجه", blank=True)
    preview_data = models.JSONField("داده موقت پیش‌نمایش", default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
