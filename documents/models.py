from django.db import models
from django.conf import settings

class DocumentRecord(models.Model):
    title = models.CharField("عنوان سند", max_length=250)
    category = models.CharField("دسته", max_length=100)
    file = models.FileField("فایل اداری", upload_to="documents/")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    company = models.ForeignKey("organizations.Company", null=True, blank=True, on_delete=models.PROTECT)
    is_confidential = models.BooleanField("محرمانه", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.title
