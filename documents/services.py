import hashlib

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max

from auditlog.services import record_event

from .models import DocumentAccessEvent, DocumentRecord, DocumentVersion


def _sha256(upload):
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


@transaction.atomic
def create_document(
    *,
    title,
    category,
    upload,
    uploaded_by,
    company=None,
    person=None,
    security_level=DocumentRecord.SecurityLevel.NORMAL,
    is_medical=False,
    change_reason="نسخه اولیه",
    request=None,
):
    if not title.strip() or not category.strip() or upload is None:
        raise ValidationError("عنوان، دسته‌بندی و فایل سند الزامی هستند.")
    digest = _sha256(upload)
    record = DocumentRecord(
        title=title.strip(),
        category=category.strip(),
        file=upload,
        uploaded_by=uploaded_by,
        company=company,
        person=person,
        security_level=security_level,
        is_medical=is_medical,
        is_confidential=security_level in {
            DocumentRecord.SecurityLevel.CONFIDENTIAL,
            DocumentRecord.SecurityLevel.VERY_CONFIDENTIAL,
        },
    )
    record.save()
    DocumentVersion.objects.create(
        document=record,
        version_number=1,
        file=record.file.name,
        uploaded_by=uploaded_by,
        change_reason=change_reason,
        checksum_sha256=digest,
        is_current=True,
    )
    record_event(
        actor=uploaded_by,
        action="document_created",
        obj=record,
        summary=f"پرونده سند ایجاد شد: {record.title}",
        after_data={
            "version": 1,
            "security_level": record.security_level,
            "is_medical": record.is_medical,
            "company_id": record.company_id,
            "person_id": record.person_id,
        },
        request=request,
    )
    return record


@transaction.atomic
def add_document_version(
    *,
    document_id,
    upload,
    uploaded_by,
    change_reason,
    request=None,
):
    document = DocumentRecord.objects.select_for_update().get(pk=document_id)
    if document.is_archived or document.is_void:
        raise ValidationError("برای سند بایگانی یا باطل‌شده نسخه جدید ثبت نمی‌شود.")
    if not change_reason.strip():
        raise ValidationError("برای ثبت نسخه جدید، شرح تغییر الزامی است.")
    current_max = document.versions.aggregate(value=Max("version_number"))["value"] or 0
    next_number = current_max + 1
    digest = _sha256(upload)
    document.versions.filter(is_current=True).update(is_current=False)
    version = DocumentVersion.objects.create(
        document=document,
        version_number=next_number,
        file=upload,
        uploaded_by=uploaded_by,
        change_reason=change_reason.strip(),
        checksum_sha256=digest,
        is_current=True,
    )
    document.file = version.file.name
    document.uploaded_by = uploaded_by
    document.save(update_fields=["file", "uploaded_by"])
    record_event(
        actor=uploaded_by,
        action="document_version_created",
        obj=document,
        summary=f"نسخه {next_number} سند ثبت شد.",
        after_data={"version_id": version.pk, "version_number": next_number, "sha256": digest},
        request=request,
    )
    return version


def record_document_access(*, document, version, actor, action, request=None):
    event = DocumentAccessEvent.objects.create(
        document=document,
        version=version,
        actor=actor,
        action=action,
        ip_address=(request.META.get("REMOTE_ADDR") if request else None),
    )
    record_event(
        actor=actor,
        action=f"document_{action}",
        obj=document,
        summary=f"دسترسی به سند: {document.title}",
        after_data={"version_id": version.pk if version else None, "access_event_id": event.pk},
        request=request,
    )
    return event


@transaction.atomic
def archive_document(*, document_id, actor, reason, request=None):
    if not reason.strip():
        raise ValidationError("دلیل بایگانی الزامی است.")
    document = DocumentRecord.objects.select_for_update().get(pk=document_id)
    if document.is_void:
        raise ValidationError("سند باطل‌شده قابل بایگانی مجدد نیست.")
    before = {"is_archived": document.is_archived}
    from django.utils import timezone
    document.is_archived = True
    document.archive_reason = reason.strip()
    document.archived_at = timezone.now()
    document.save(update_fields=["is_archived", "archive_reason", "archived_at"])
    record_event(
        actor=actor, action="document_archived", obj=document,
        summary="سند بایگانی شد.", before_data=before,
        after_data={"is_archived": True, "archive_reason": document.archive_reason},
        request=request,
    )
    return document


@transaction.atomic
def void_document(*, document_id, actor, reason, request=None):
    if not reason.strip():
        raise ValidationError("دلیل ابطال الزامی است.")
    document = DocumentRecord.objects.select_for_update().get(pk=document_id)
    if document.is_void:
        raise ValidationError("سند قبلاً باطل شده است.")
    before = {"is_void": document.is_void}
    from django.utils import timezone
    document.is_void = True
    document.void_reason = reason.strip()
    document.voided_at = timezone.now()
    document.save(update_fields=["is_void", "void_reason", "voided_at"])
    record_event(
        actor=actor, action="document_voided", obj=document,
        summary="سند باطل شد.", before_data=before,
        after_data={"is_void": True, "void_reason": document.void_reason},
        request=request,
    )
    return document
