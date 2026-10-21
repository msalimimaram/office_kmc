from django.db import models
from django.conf import settings

class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField("عملیات", max_length=120)
    object_type = models.CharField("نوع رکورد", max_length=120, blank=True)
    object_id = models.CharField("شناسه رکورد", max_length=100, blank=True)
    summary = models.TextField("شرح", blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        ordering = ["-created_at"]
