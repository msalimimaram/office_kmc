from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Exists, OuterRef, Q
from django.contrib.contenttypes.models import ContentType
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
from core.permissions import scoped_claims_for, scoped_requests_for
from core.uploads import validate_uploaded_file
from organizations.models import Company, Person, PersonEmployment
from .models import DocumentRecord, DocumentVersion, DocumentLink
from .forms import DocumentLifecycleActionForm, DocumentVersionForm, DocumentLinkForm
from auditlog.services import record_event


def records_in_company_employment_period(queryset, company_ids, *, person_field, timestamp_field):
    """Limit person-linked records to the company employing that person when recorded."""
    company_ids = tuple(company_ids or ())
    if not company_ids:
        return queryset.none()
    employment_at_record_time = PersonEmployment.objects.filter(
        person_id=OuterRef(f"{person_field}_id"),
        company_id__in=company_ids,
    ).filter(
        Q(valid_from__isnull=True)
        | Q(valid_from__lte=OuterRef(f"{timestamp_field}__date"))
    ).filter(
        Q(valid_until__isnull=True)
        | Q(valid_until__gte=OuterRef(f"{timestamp_field}__date"))
    )
    return queryset.filter(Exists(employment_at_record_time))

from .services import (
    add_document_version, archive_document, create_document,
    record_document_access, void_document,
)


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
        # Confidential documents require an explicit relationship to a claim
        # inside the specialist's line scope. Unlinked global reference material
        # is limited to NORMAL/INTERNAL; otherwise an unscoped confidential file
        # would be visible to every specialist.
        scoped_claim_documents = qs.filter(
            pk__in=claim_ct,
            is_medical=False,
            security_level__in=[
                DocumentRecord.SecurityLevel.NORMAL,
                DocumentRecord.SecurityLevel.INTERNAL,
                DocumentRecord.SecurityLevel.CONFIDENTIAL,
            ],
        )
        global_reference_documents = qs.filter(
            company__isnull=True,
            person__isnull=True,
            is_medical=False,
            security_level__in=[
                DocumentRecord.SecurityLevel.NORMAL,
                DocumentRecord.SecurityLevel.INTERNAL,
            ],
        )
        allowed_ids.update(scoped_claim_documents.values_list("pk", flat=True))
        allowed_ids.update(global_reference_documents.values_list("pk", flat=True))

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        company_document_scope = qs.filter(
            is_medical=False,
            security_level__in=[
                DocumentRecord.SecurityLevel.NORMAL,
                DocumentRecord.SecurityLevel.INTERNAL,
                DocumentRecord.SecurityLevel.CONFIDENTIAL,
            ],
        )
        allowed_ids.update(
            company_document_scope.filter(
                company_id__in=company_ids
            ).values_list("pk", flat=True)
        )
        # Person-owned documents follow the employment period at the time the
        # document was created. A former employer must not inherit access to
        # documents uploaded after the employee transferred elsewhere.
        person_document_scope = records_in_company_employment_period(
            company_document_scope.filter(person__isnull=False),
            company_ids,
            person_field="person",
            timestamp_field="created_at",
        )
        allowed_ids.update(person_document_scope.values_list("pk", flat=True))

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


def _document_link_target_queryset(user, target_type):
    """Return the existing app-level visibility scope for a link target."""
    if target_type == "claim":
        from claims.models import Claim
        return scoped_claims_for(user).select_related("person", "primary_insured", "company_snapshot")
    if target_type == "request":
        from requests_portal.models import ServiceRequest
        return scoped_requests_for(user).select_related("person", "company")
    if target_type == "correspondence":
        from correspondence.models import Correspondence
        from correspondence.views import _scope
        return _scope(user).select_related("company", "insurer")
    if target_type == "contract":
        from insurance.models import Contract
        from insurance.views import _contract_scope
        return _contract_scope(user).prefetch_related("companies")
    if target_type == "asset":
        from assets.models import InsuredAsset
        from assets.views import _asset_scope
        return _asset_scope(user).select_related("company", "person")
    if target_type == "task":
        from tasks.models import InternalTask
        from tasks.views import _visible_tasks
        return _visible_tasks(user).select_related("related_request__person", "related_request__company")
    return None


def _document_link_target_company_and_people(target_type, target):
    company_ids = set()
    person_ids = set()
    if target_type == "claim":
        if target.company_snapshot_id:
            company_ids.add(target.company_snapshot_id)
        person_ids.update(pk for pk in (target.person_id, target.primary_insured_id) if pk)
    elif target_type == "request":
        company_id = target.company_id or (target.person.company_id if target.person_id else None)
        if company_id:
            company_ids.add(company_id)
        if target.person_id:
            person_ids.add(target.person_id)
    elif target_type == "correspondence":
        if target.company_id:
            company_ids.add(target.company_id)
    elif target_type == "contract":
        company_ids.update(target.companies.values_list("pk", flat=True))
    elif target_type == "asset":
        company_id = target.company_id or (target.person.company_id if target.person_id else None)
        if company_id:
            company_ids.add(company_id)
        if target.person_id:
            person_ids.add(target.person_id)
    elif target_type == "task" and target.related_request_id:
        request = target.related_request
        company_id = request.company_id or (request.person.company_id if request.person_id else None)
        if company_id:
            company_ids.add(company_id)
        if request.person_id:
            person_ids.add(request.person_id)
    return company_ids, person_ids


def _resolve_document_link_target(user, document, target_type, target_id):
    queryset = _document_link_target_queryset(user, target_type)
    if queryset is None:
        return None, None
    target = queryset.filter(pk=target_id).first()
    if target is None:
        return None, None

    company_ids, person_ids = _document_link_target_company_and_people(target_type, target)
    if document.company_id and document.company_id not in company_ids:
        raise PermissionDenied("رکورد مقصد با شرکت ثبت‌شده روی سند سازگار نیست.")
    if document.person_id and document.person_id not in person_ids:
        raise PermissionDenied("رکورد مقصد با شخص ثبت‌شده روی سند سازگار نیست.")

    content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
    return target, content_type



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
        is_confidential = request.POST.get("is_confidential") == "on"
        if is_confidential and security_level == DocumentRecord.SecurityLevel.NORMAL:
            security_level = DocumentRecord.SecurityLevel.CONFIDENTIAL
        if is_medical:
            security_level = DocumentRecord.SecurityLevel.VERY_CONFIDENTIAL
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
            if not has_global_access(user):
                raise PermissionDenied("اتصال سند به یک شرکت مشخص فقط برای رئیس اداره یا مدیر سامانه مجاز است.")
            company = get_object_or_404(Company, pk=company_id, is_active=True)
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, "documents/document_upload.html", {
                "companies": Company.objects.filter(is_active=True) if has_global_access(user) else Company.objects.none(),
                "security_levels": DocumentRecord.SecurityLevel.choices,
                "can_upload_medical": has_global_access(user),
                "title": title,
                "category": category,
                "selected_company": company_id,
                "security_level": security_level,
                "is_medical": is_medical,
                "is_confidential": is_confidential,
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
        "companies": Company.objects.filter(is_active=True) if has_global_access(user) else Company.objects.none(),
        "security_levels": DocumentRecord.SecurityLevel.choices,
        "can_upload_medical": has_global_access(user),
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



@login_required
def document_manage(request, pk):
    """Manage versions and lifecycle of a document within the existing access scope."""
    user = request.user
    document = get_object_or_404(_visible_documents(user), pk=pk)
    can_add_version = has_global_access(user) or has_role(
        user, RoleAssignment.Role.INSURANCE_SPECIALIST
    )
    can_manage_lifecycle = has_global_access(user)

    version_form = DocumentVersionForm()
    lifecycle_form = DocumentLifecycleActionForm()
    link_form = DocumentLinkForm()

    if request.method == "POST":
        action = request.POST.get("action", "").strip()
        if action == "add_version":
            if not can_add_version:
                raise PermissionDenied
            version_form = DocumentVersionForm(request.POST, request.FILES)
            if version_form.is_valid():
                upload = version_form.cleaned_data["file"]
                error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
                if error:
                    version_form.add_error("file", error)
                else:
                    try:
                        add_document_version(
                            document_id=document.pk,
                            upload=upload,
                            uploaded_by=user,
                            change_reason=version_form.cleaned_data["change_reason"],
                            request=request,
                        )
                    except ValidationError as exc:
                        version_form.add_error(None, exc)
                    else:
                        messages.success(request, "نسخه جدید سند با موفقیت ثبت شد.")
                        return redirect("document_manage", pk=document.pk)
        elif action == "add_link":
            if not can_add_version or document.is_archived or document.is_void:
                raise PermissionDenied
            link_form = DocumentLinkForm(request.POST)
            if link_form.is_valid():
                target_type = link_form.cleaned_data["target_type"]
                target_id = link_form.cleaned_data["target_id"]
                target, content_type = _resolve_document_link_target(
                    user, document, target_type, target_id
                )
                if target is None:
                    link_form.add_error(None, "رکورد مقصد در محدوده دسترسی شما یافت نشد.")
                elif DocumentLink.objects.filter(
                    document=document, content_type=content_type, object_id=str(target.pk)
                ).exists():
                    link_form.add_error(None, "این سند قبلاً به همین رکورد متصل شده است.")
                else:
                    with transaction.atomic():
                        link = DocumentLink.objects.create(
                            document=document,
                            content_type=content_type,
                            object_id=str(target.pk),
                            created_by=user,
                        )
                        record_event(
                            actor=user,
                            action="document_link_created",
                            obj=document,
                            summary="سند به یک رکورد عملیاتی متصل شد.",
                            after_data={
                                "link_id": link.pk,
                                "target_type": target_type,
                                "target_id": str(target.pk),
                            },
                            request=request,
                        )
                    messages.success(request, "سند با موفقیت به رکورد انتخاب‌شده متصل شد.")
                    return redirect("document_manage", pk=document.pk)
        elif action in {"archive", "void"}:
            if not can_manage_lifecycle:
                raise PermissionDenied
            lifecycle_form = DocumentLifecycleActionForm(request.POST)
            if lifecycle_form.is_valid():
                reason = lifecycle_form.cleaned_data["reason"]
                try:
                    if action == "archive":
                        archive_document(
                            document_id=document.pk, actor=user, reason=reason, request=request
                        )
                        messages.success(request, "سند با دلیل ثبت‌شده بایگانی شد.")
                    else:
                        void_document(
                            document_id=document.pk, actor=user, reason=reason, request=request
                        )
                        messages.success(request, "سند با دلیل ثبت‌شده باطل شد.")
                except ValidationError as exc:
                    lifecycle_form.add_error(None, exc)
                else:
                    return redirect("document_manage", pk=document.pk)
        else:
            raise PermissionDenied("عملیات درخواستی برای مدیریت سند معتبر نیست.")

    document.refresh_from_db()
    versions = document.versions.select_related("uploaded_by").order_by("-version_number")
    visible_links = []
    if can_add_version:
        for link in document.links.select_related("content_type", "created_by").order_by("-created_at"):
            target_type = next(
                (
                    choice
                    for choice, _label in DocumentLinkForm.TARGET_CHOICES
                    if (link.content_type.app_label, link.content_type.model) == {
                        "claim": ("claims", "claim"),
                        "request": ("requests_portal", "servicerequest"),
                        "correspondence": ("correspondence", "correspondence"),
                        "contract": ("insurance", "contract"),
                        "asset": ("assets", "insuredasset"),
                        "task": ("tasks", "internaltask"),
                    }[choice]
                ),
                None,
            )
            if target_type:
                target, _content_type = _resolve_document_link_target(
                    user, document, target_type, link.object_id
                )
                if target is not None:
                    visible_links.append({"link": link, "target": target})
    return render(request, "documents/document_manage.html", {
        "document": document,
        "versions": versions,
        "version_form": version_form,
        "lifecycle_form": lifecycle_form,
        "link_form": link_form,
        "visible_links": visible_links,
        "can_add_version": can_add_version and not document.is_archived and not document.is_void,
        "can_manage_lifecycle": can_manage_lifecycle,
        "can_archive": can_manage_lifecycle and not document.is_archived and not document.is_void,
        "can_void": can_manage_lifecycle and not document.is_void,
    })
