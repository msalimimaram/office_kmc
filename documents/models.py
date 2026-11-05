from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ImmutableDocumentRecordQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("پرونده سند فقط از مسیر سرویس‌های کنترل‌شده قابل تغییر است.")

    def delete(self):
        raise ValidationError("پرونده سند حذف نمی‌شود؛ از بایگانی یا ابطال استفاده کنید.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی پرونده اسناد مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی پرونده سند خارج از سرویس مجاز نیست.")


class ImmutableDocumentVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("نسخه سند ویرایش نمی‌شود؛ نسخه جدید ثبت کنید.")

    def delete(self):
        raise ValidationError("نسخه سند حذف نمی‌شود.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی نسخه اسناد مجاز نیست.")

    def _mark_previous_not_current(self):
        # Internal transition used only when a new immutable version is added.
        return super().update(is_current=False)


class DocumentRecord(models.Model):
    objects = ImmutableDocumentRecordQuerySet.as_manager()

    class SecurityLevel(models.TextChoices):
        NORMAL = "normal", "عادی"
        INTERNAL = "internal", "داخلی"
        CONFIDENTIAL = "confidential", "محرمانه"
        VERY_CONFIDENTIAL = "very_confidential", "بسیار محرمانه"

    title = models.CharField("عنوان سند", max_length=250)
    category = models.CharField("دسته", max_length=100)
    file = models.FileField("نسخه جاری سند", upload_to="documents/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_documents"
    )
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="documents",
    )
    person = models.ForeignKey(
        "organizations.Person", null=True, blank=True, on_delete=models.PROTECT,
        related_name="documents",
    )
    security_level = models.CharField(
        "سطح محرمانگی", max_length=24, choices=SecurityLevel.choices, default=SecurityLevel.NORMAL
    )
    is_medical = models.BooleanField("سند پزشکی", default=False)
    is_confidential = models.BooleanField("محرمانه (سازگاری قدیمی)", default=False)
    is_archived = models.BooleanField("بایگانی شده", default=False)
    archived_at = models.DateTimeField("زمان بایگانی", null=True, blank=True)
    archive_reason = models.TextField("دلیل بایگانی", blank=True)
    is_void = models.BooleanField("باطل شده", default=False)
    voided_at = models.DateTimeField("زمان ابطال", null=True, blank=True)
    void_reason = models.TextField("دلیل ابطال", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = "پرونده سند"
        verbose_name_plural = "پرونده‌های اسناد"
        constraints = [
            models.CheckConstraint(
                condition=~Q(is_archived=True) | Q(archive_reason__gt=""),
                name="document_archive_requires_reason",
            ),
            models.CheckConstraint(
                condition=~Q(is_void=True) | Q(void_reason__gt=""),
                name="document_void_requires_reason",
            ),
        ]

    def clean(self):
        super().clean()
        if self.is_medical:
            self.security_level = self.SecurityLevel.VERY_CONFIDENTIAL
            self.is_confidential = True
        if self.is_confidential and self.security_level == self.SecurityLevel.NORMAL:
            self.security_level = self.SecurityLevel.CONFIDENTIAL
        if self.is_archived and not self.archive_reason.strip():
            raise ValidationError({"archive_reason": "برای بایگانی سند، درج دلیل الزامی است."})
        if self.is_void and not self.void_reason.strip():
            raise ValidationError({"void_reason": "برای ابطال سند، درج دلیل الزامی است."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def current_version(self):
        return self.versions.filter(is_current=True).first()

    def delete(self, *args, **kwargs):
        raise ValidationError("پرونده سند حذف نمی‌شود؛ از بایگانی یا ابطال استفاده کنید.")

    def __str__(self):
        return self.title


class DocumentVersion(models.Model):
    objects = ImmutableDocumentVersionQuerySet.as_manager()
    document = models.ForeignKey(DocumentRecord, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField("شماره نسخه")
    file = models.FileField("فایل نسخه", upload_to="document_versions/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="document_versions_uploaded"
    )
    change_reason = models.TextField("شرح تغییر", blank=True)
    checksum_sha256 = models.CharField("SHA256", max_length=64, blank=True)
    is_current = models.BooleanField("نسخه جاری", default=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("document_id", "-version_number")
        constraints = [
            models.UniqueConstraint(fields=("document", "version_number"), name="uniq_document_version"),
            models.UniqueConstraint(fields=("document",), condition=Q(is_current=True), name="uniq_document_current_version"),
        ]
        verbose_name = "نسخه سند"
        verbose_name_plural = "نسخه‌های سند"

    def clean(self):
        super().clean()
        if self.version_number < 1:
            raise ValidationError({"version_number": "شماره نسخه باید حداقل یک باشد."})
        if self.is_current and self.document_id:
            if self.document.is_archived or self.document.is_void:
                raise ValidationError("برای سند بایگانی یا باطل‌شده نسخه جاری جدید ثبت نمی‌شود.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("نسخه ثبت‌شده سند ویرایش نمی‌شود؛ نسخه جدید ایجاد کنید.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("نسخه سند حذف نمی‌شود.")

    def __str__(self):
        return f"{self.document} — v{self.version_number}"


class DocumentLink(models.Model):
    """Generic links let one document relate to multiple business objects."""

    document = models.ForeignKey(DocumentRecord, on_delete=models.PROTECT, related_name="links")
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey("content_type", "object_id")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("document", "content_type", "object_id"), name="uniq_document_link"),
        ]
        indexes = [models.Index(fields=("content_type", "object_id"), name="document_link_target")]
        verbose_name = "ارتباط سند"
        verbose_name_plural = "ارتباط‌های سند"


class ImmutableDocumentAccessQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("رویداد دسترسی سند قابل ویرایش نیست.")

    def delete(self):
        raise ValidationError("رویداد دسترسی سند قابل حذف نیست.")


class DocumentAccessEvent(models.Model):
    class Action(models.TextChoices):
        VIEW = "view", "مشاهده"
        DOWNLOAD = "download", "دریافت"
        PRINT = "print", "چاپ"
        EXPORT = "export", "خروجی"

    document = models.ForeignKey(DocumentRecord, on_delete=models.PROTECT, related_name="access_events")
    version = models.ForeignKey(
        DocumentVersion, null=True, blank=True, on_delete=models.PROTECT, related_name="access_events"
    )
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=12, choices=Action.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at", "-pk")
        verbose_name = "رویداد دسترسی سند"
        verbose_name_plural = "رویدادهای دسترسی اسناد"

    objects = ImmutableDocumentAccessQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد دسترسی سند قابل ویرایش نیست.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویداد دسترسی سند قابل حذف نیست.")
