from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.db import models
from django.utils.text import get_valid_filename

from .models import DocumentRecord
from auditlog.models import AuditEvent

STAFF_ROLES = {"system_admin", "department_head", "insurance_specialist"}


def _visible_documents(user):
    qs = DocumentRecord.objects.select_related("uploaded_by", "company")
    if user.is_superuser or user.role in STAFF_ROLES:
        return qs
    if user.role == "auditor":
        return qs.filter(is_confidential=False)
    if user.role in {"subsidiary_rep", "employee", "finance", "legal", "insurer"}:
        if not user.company_id:
            return qs.filter(company__isnull=True, is_confidential=False)
        return qs.filter(is_confidential=False).filter(
            models.Q(company=user.company) | models.Q(company__isnull=True)
        )
    return qs.none()


@login_required
def document_list(request):
    return render(request, "documents/document_list.html", {
        "documents": _visible_documents(request.user),
        "can_upload": request.user.is_superuser or request.user.role in STAFF_ROLES,
    })


@login_required
def document_upload(request):
    if not (request.user.is_superuser or request.user.role in STAFF_ROLES):
        raise PermissionDenied
    from django import forms
    from organizations.models import Company

    if request.method == "POST":
        title = request.POST.get("title", "").strip()[:250]
        category = request.POST.get("category", "").strip()[:100]
        upload = request.FILES.get("file")
        confidential = request.POST.get("is_confidential") == "on"
        company_id = request.POST.get("company") or None
        errors = []
        if not title:
            errors.append("عنوان سند الزامی است.")
        if not category:
            errors.append("دسته‌بندی سند الزامی است.")
        if not upload:
            errors.append("انتخاب فایل الزامی است.")
        elif upload.size > 20 * 1024 * 1024:
            errors.append("حداکثر حجم فایل ۲۰ مگابایت است.")
        elif Path(upload.name).suffix.lower() not in {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}:
            errors.append("نوع فایل مجاز نیست. فقط PDF، DOCX، XLSX و تصویر پشتیبانی می‌شوند.")
        company = None
        if company_id:
            company = get_object_or_404(Company, pk=company_id)
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, "documents/document_upload.html", {
                "companies": Company.objects.filter(is_active=True), "title": title,
                "category": category, "selected_company": company_id,
                "is_confidential": confidential,
            })
        record = DocumentRecord.objects.create(
            title=title, category=category, file=upload, uploaded_by=request.user,
            company=company, is_confidential=confidential,
        )
        AuditEvent.objects.create(
            actor=request.user, action="document_uploaded", object_type="DocumentRecord",
            object_id=str(record.pk), summary=f"سند بارگذاری شد: {record.title}",
        )
        messages.success(request, "سند با موفقیت ثبت شد.")
        return redirect("document_list")
    return render(request, "documents/document_upload.html", {
        "companies": Company.objects.filter(is_active=True),
    })


@login_required
def document_download(request, pk):
    record = get_object_or_404(_visible_documents(request.user), pk=pk)
    try:
        handle = record.file.open("rb")
    except (OSError, ValueError):
        raise Http404("فایل در دسترس نیست.")
    filename = get_valid_filename(Path(record.file.name).name) or f"document-{record.pk}"
    AuditEvent.objects.create(
        actor=request.user, action="document_downloaded", object_type="DocumentRecord",
        object_id=str(record.pk), summary=f"دانلود سند: {record.title}",
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
