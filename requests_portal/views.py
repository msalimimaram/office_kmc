import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.access import company_ids_for, has_global_access, has_role
from accounts.models import RoleAssignment, User
from auditlog.services import record_event
from core.permissions import can_process_request, can_transition_request, scoped_requests_for
from .forms import ServiceRequestForm
from .models import ServiceRequest


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
