from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.db import models
from django.utils.text import get_valid_filename

from accounts.access import (
    company_ids_for,
    has_global_access,
    has_role,
    insurer_ids_for,
    line_codes_for,
)
from accounts.models import RoleAssignment
from claims.models import Claim
from core.permissions import scoped_claims_for
from core.uploads import validate_uploaded_file
from organizations.models import Company, Person, PersonEmployment
from .models import DocumentRecord, DocumentVersion, DocumentLink
from .services import create_document, record_document_access


def _visible_documents(user):
    qs = DocumentRecord.objects.select_related(
        "uploaded_by", "company", "person"
    ).prefetch_related("versions")
    if has_global_access(user):
        return qs

    allowed_ids = set()

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        line_codes = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        claims = Claim.objects.all() if "*" in line_codes else Claim.objects.filter(contract__line__in=line_codes)
        claim_ct = DocumentLink.objects.filter(
            content_type__app_label="claims",
            content_type__model="claim",
            object_id__in=claims.values_list("pk", flat=True),
        ).values_list("document_id", flat=True)
        allowed_ids.update(
            qs.filter(
                is_medical=False,
                security_level__in=[
                    DocumentRecord.SecurityLevel.NORMAL,
                    DocumentRecord.SecurityLevel.INTERNAL,
                    DocumentRecord.SecurityLevel.CONFIDENTIAL,
                ],
            ).filter(
                models.Q(pk__in=claim_ct)
                | models.Q(company__isnull=True, person__isnull=True)
            ).values_list("pk", flat=True)
        )

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        people_ids = PersonEmployment.objects.filter(
            company_id__in=company_ids
        ).values_list("person_id", flat=True)
        allowed_ids.update(
            qs.filter(
                is_medical=False,
                security_level__in=[
                    DocumentRecord.SecurityLevel.NORMAL,
                    DocumentRecord.SecurityLevel.INTERNAL,
                    DocumentRecord.SecurityLevel.CONFIDENTIAL,
                ],
            ).filter(
                models.Q(company_id__in=company_ids)
                | models.Q(person_id__in=people_ids)
            ).values_list("pk", flat=True)
        )

    insurer_ids = insurer_ids_for(user)
    if insurer_ids:
        claim_ids = Claim.objects.filter(
            insurer_id__in=insurer_ids
        ).values_list("pk", flat=True)
        insurer_document_ids = DocumentLink.objects.filter(
            content_type__app_label="claims",
            content_type__model="claim",
            object_id__in=claim_ids,
        ).values_list("document_id", flat=True)
        allowed_ids.update(
            qs.filter(
                pk__in=insurer_document_ids,
                is_medical=False,
                security_level__in=[
                    DocumentRecord.SecurityLevel.NORMAL,
                    DocumentRecord.SecurityLevel.INTERNAL,
                ],
            ).values_list("pk", flat=True)
        )

    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        person_ids = Person.objects.filter(
            models.Q(user_id=user.pk) | models.Q(employee__user_id=user.pk)
        ).values_list("pk", flat=True)
        claims = scoped_claims_for(user).values_list("pk", flat=True)
        claim_document_ids = DocumentLink.objects.filter(
            content_type__app_label="claims",
            content_type__model="claim",
            object_id__in=claims,
        ).values_list("document_id", flat=True)
        allowed_ids.update(
            qs.filter(
                is_medical=False,
                security_level__in=[
                    DocumentRecord.SecurityLevel.NORMAL,
                    DocumentRecord.SecurityLevel.INTERNAL,
                ],
            ).filter(
                models.Q(person_id__in=person_ids)
                | models.Q(pk__in=claim_document_ids)
            ).values_list("pk", flat=True)
        )

    return qs.filter(pk__in=allowed_ids, is_medical=False).distinct()


@login_required
def document_list(request):
    records = _visible_documents(request.user)
    page_obj = Paginator(records.order_by("-created_at", "-pk"), 25).get_page(request.GET.get("page"))
    can_upload = has_global_access(request.user) or has_role(
        request.user, RoleAssignment.Role.INSURANCE_SPECIALIST
    )
    return render(request, "documents/document_list.html", {
        "documents": page_obj.object_list,
        "page_obj": page_obj,
        "can_upload": can_upload,
    })


@login_required
def document_upload(request):
    user = request.user
    if not (has_global_access(user) or has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)):
        raise PermissionDenied

    if request.method == "POST":
        title = request.POST.get("title", "").strip()[:250]
        category = request.POST.get("category", "").strip()[:100]
        upload = request.FILES.get("file")
        security_level = request.POST.get("security_level", DocumentRecord.SecurityLevel.NORMAL)
        is_medical = request.POST.get("is_medical") == "on"
        company_id = request.POST.get("company") or None
        errors = []
        if not title:
            errors.append("عنوان سند الزامی است.")
        if not category:
            errors.append("دسته‌بندی سند الزامی است.")
        if security_level not in dict(DocumentRecord.SecurityLevel.choices):
            errors.append("سطح محرمانگی انتخاب‌شده معتبر نیست.")
        if is_medical and not has_global_access(user):
            errors.append("بارگذاری مدرک پزشکی فقط برای رئیس اداره و مدیر سامانه مجاز است.")
        if upload:
            file_error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
            if file_error:
                errors.append(file_error)
        else:
            errors.append("انتخاب فایل الزامی است.")

        company = None
        if company_id:
            company = get_object_or_404(Company, pk=company_id, is_active=True)
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, "documents/document_upload.html", {
                "companies": Company.objects.filter(is_active=True),
                "title": title,
                "category": category,
                "selected_company": company_id,
                "security_level": security_level,
                "is_medical": is_medical,
            })

        record = create_document(
            title=title,
            category=category,
            upload=upload,
            uploaded_by=user,
            company=company,
            security_level=security_level,
            is_medical=is_medical,
            request=request,
        )
        messages.success(request, "سند و نسخه اولیه آن با موفقیت ثبت شد.")
        return redirect("document_list")

    return render(request, "documents/document_upload.html", {
        "companies": Company.objects.filter(is_active=True),
        "security_levels": DocumentRecord.SecurityLevel.choices,
    })


@login_required
def document_download(request, pk):
    record = get_object_or_404(_visible_documents(request.user), pk=pk)
    if record.is_archived or record.is_void:
        raise Http404("سند بایگانی یا باطل شده است.")
    version = record.current_version
    if version is None:
        raise Http404("نسخه جاری سند در دسترس نیست.")
    try:
        handle = version.file.open("rb")
    except (OSError, ValueError):
        raise Http404("فایل در دسترس نیست.")
    filename = get_valid_filename(Path(version.file.name).name) or f"document-{record.pk}"
    record_document_access(
        document=record,
        version=version,
        actor=request.user,
        action="download",
        request=request,
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
