import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.access import company_ids_for, has_global_access, has_role
from accounts.models import RoleAssignment, User
from auditlog.services import record_event
from core.permissions import can_process_request, can_transition_request, scoped_requests_for
from .forms import ServiceRequestForm
from .models import ServiceRequest
from django.contrib.contenttypes.models import ContentType
from workflow.models import WorkflowCase, WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow


def _initial_company_id(user):
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        return next(iter(ids)) if len(ids) == 1 else None
    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        person = getattr(user, "person_record", None)
        if person and person.company_id:
            return person.company_id
        return getattr(user, "company_id", None)
    return None


def _first_company_representative(company_id):
    if not company_id:
        return None
    today = timezone.localdate()
    return User.objects.filter(
        role_assignments__role=RoleAssignment.Role.SUBSIDIARY_REP,
        role_assignments__company_id=company_id,
        role_assignments__is_active=True,
        is_active=True,
        role_assignments__valid_from__lte=today,
    ).filter(
        models.Q(role_assignments__valid_until__isnull=True)
        | models.Q(role_assignments__valid_until__gte=today)
    ).distinct().order_by("pk").first()


@login_required
def request_list(request):
    qs = scoped_requests_for(request.user).order_by("-created_at", "-pk")
    page_obj = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "requests_portal/request_list.html", {
        "requests_list": page_obj.object_list,
        "page_obj": page_obj,
    })


@login_required
def request_create(request):
    user = request.user
    allowed = has_global_access(user) or any(
        has_role(user, role)
        for role in (
            RoleAssignment.Role.SUBSIDIARY_REP,
            RoleAssignment.Role.INSURED_PERSON,
        )
    )
    if not allowed:
        raise PermissionDenied

    company_id = _initial_company_id(user)
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) and not company_id:
        raise PermissionDenied("ابتدا شرکت فعال را انتخاب کنید.")

    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES, user=user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    item = form.save(commit=False)
                    item.submitted_by = user
                    item.company_id = company_id or getattr(user, "company_id", None)
                    item.person = form.cleaned_data.get("person")
                    item.reference = "IB-" + secrets.token_hex(5).upper()
                    item.is_confidential = item.kind == ServiceRequest.Kind.MEDICAL_ASSISTANCE
                    if has_role(user, RoleAssignment.Role.INSURED_PERSON) and not has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
                        item.assigned_to = _first_company_representative(item.company_id)
                    item.save()
                    active_definition = WorkflowDefinition.objects.filter(
                        code=item.kind, is_active=True
                    ).order_by("-version").first()
                    if not active_definition:
                        raise ValidationError(
                            f"گردش‌کار فعال و منتشرشده برای نوع درخواست «{item.get_kind_display()}» تعریف نشده است؛ "
                            "ثبت درخواست تا زمان انتشار گردش‌کار مجاز نیست."
                        )
                    initial_assignee, delegation = resolve_initial_assignee(
                        definition=active_definition,
                        obj=item,
                        return_delegation=True,
                        company_id=item.company_id,
                        line_code="health" if item.kind in {
                            ServiceRequest.Kind.MEDICAL_ASSISTANCE,
                            ServiceRequest.Kind.ANONYMOUS_PLAN,
                            ServiceRequest.Kind.EXCESS_COVERAGE,
                            ServiceRequest.Kind.ADD_COVERAGE,
                            ServiceRequest.Kind.REMOVE_COVERAGE,
                            ServiceRequest.Kind.BASE_INSURANCE_WAIVER,
                        } else None,
                        owner_user_id=user.pk,
                        # Keep a company representative eligible to receive their own request.
                        exclude_user_id=(
                            user.pk if has_role(user, RoleAssignment.Role.INSURED_PERSON)
                            and not has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) else None
                        ),
                    )
                    start_workflow(
                        obj=item,
                        code=item.kind,
                        actor=user,
                        assignee=initial_assignee,
                        delegation=delegation,
                        note="درخواست توسط کاربر ثبت شد.",
                    )
                    item.assigned_to = initial_assignee
                    item.save(update_fields=["assigned_to", "updated_at"])
                    record_event(
                        actor=user,
                        action="service_request_created",
                        obj=item,
                        summary=f"درخواست {item.reference} ثبت شد",
                        after_data={
                            "reference": item.reference,
                            "kind": item.kind,
                            "company_id": item.company_id,
                            "person_id": item.person_id,
                            "assigned_to_id": item.assigned_to_id,
                        },
                        request=request,
                    )
            except ValidationError as exc:
                # A broken workflow definition/recipient assignment must never
                # produce a half-created request or an unhandled server error.
                form.add_error(None, exc)
            else:
                messages.success(request, f"درخواست شما با شماره پیگیری {item.reference} ثبت شد.")
                return redirect("request_list")
    else:
        form = ServiceRequestForm(user=user)
    return render(request, "requests_portal/request_form.html", {"form": form})


@login_required
def request_detail(request, pk):
    item = get_object_or_404(scoped_requests_for(request.user), pk=pk)
    user = request.user
    can_process = can_process_request(user, item)
    content_type = ContentType.objects.get_for_model(item, for_concrete_model=False)
    workflow_case = WorkflowCase.objects.filter(content_type=content_type, object_id=str(item.pk)).select_related("current_assignee").first()
    if workflow_case and (has_global_access(user) or workflow_case.current_assignee_id == user.pk):
        return redirect("workflow_case_detail", pk=workflow_case.pk)

    if request.method == "POST":
        if not can_process:
            raise PermissionDenied
        status = request.POST.get("status")
        if status not in dict(ServiceRequest.Status.choices):
            raise PermissionDenied
        if not can_transition_request(user, item, status):
            raise PermissionDenied("این اقدام در مرحله فعلی یا برای انتصاب شما مجاز نیست.")

        response_text = request.POST.get("response", "").strip()[:10000]
        if status in {ServiceRequest.Status.NEEDS_INFO, ServiceRequest.Status.REJECTED} and not response_text:
            messages.error(request, "برای درخواست اطلاعات تکمیلی یا رد درخواست، درج توضیح الزامی است.")
            return redirect("request_detail", pk=item.pk)

        with transaction.atomic():
            item = get_object_or_404(
                scoped_requests_for(user).select_for_update(), pk=pk
            )
            if not can_process_request(user, item) or not can_transition_request(user, item, status):
                raise PermissionDenied
            previous_status = item.status
            previous_assignee = item.assigned_to_id
            item.status = status
            if response_text:
                stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
                actor_name = user.get_full_name() or user.get_username()
                entry = f"[{stamp} | {actor_name} | {status}]\n{response_text}"
                item.response = f"{item.response.rstrip()}\n\n{entry}".strip() if item.response else entry
            item.save(update_fields=["status", "response", "updated_at"])
            record_event(
                actor=user,
                action="service_request_updated",
                obj=item,
                summary=f"وضعیت درخواست از {previous_status} به {status} تغییر کرد",
                before_data={"status": previous_status, "assigned_to_id": previous_assignee},
                after_data={"status": status, "assigned_to_id": item.assigned_to_id},
                request=request,
            )
        messages.success(request, "درخواست به‌روزرسانی شد.")
        return redirect("request_detail", pk=item.pk)

    allowed_statuses = [(item.status, item.get_status_display())]
    if can_process:
        allowed_statuses.extend(
            (key, label)
            for key, label in ServiceRequest.Status.choices
            if key != item.status and can_transition_request(user, item, key)
        )
    return render(request, "requests_portal/request_detail.html", {
        "item": item,
        "statuses": allowed_statuses,
        "can_process": can_process,
    })



@login_required
def request_attachment_download(request, pk):
    """Download a non-medical request attachment after applying the request's normal visibility scope."""
    item = get_object_or_404(scoped_requests_for(request.user), pk=pk)
    # Medical/confidential request attachments are never exposed through the
    # generic administrative attachment endpoint, even to the request owner.
    if item.is_confidential and not has_global_access(request.user):
        raise PermissionDenied("دسترسی به پیوست درخواست محرمانه فقط برای رئیس اداره و مدیر سامانه مجاز است.")
    if not item.attachment:
        raise Http404("برای این درخواست پیوستی ثبت نشده است.")

    try:
        attachment = item.attachment.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("فایل پیوست در دسترس نیست.")

    filename = item.attachment.name.rsplit("/", 1)[-1]
    record_event(
        actor=request.user,
        action="service_request_attachment_downloaded",
        obj=item,
        summary=f"پیوست درخواست {item.reference} دریافت شد",
        metadata={"filename": filename},
        request=request,
    )
    return FileResponse(attachment, as_attachment=True, filename=filename)
