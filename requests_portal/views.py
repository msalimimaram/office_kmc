import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import ServiceRequest
from .forms import ServiceRequestForm
from core.permissions import scoped_requests_for, PRIVILEGED
from auditlog.models import AuditEvent


TRANSITIONS = {
    ServiceRequest.Status.SUBMITTED: {
        ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.NEEDS_INFO,
        ServiceRequest.Status.REFERRED, ServiceRequest.Status.REJECTED,
    },
    ServiceRequest.Status.IN_REVIEW: {
        ServiceRequest.Status.NEEDS_INFO, ServiceRequest.Status.REFERRED,
        ServiceRequest.Status.APPROVED, ServiceRequest.Status.REJECTED,
        ServiceRequest.Status.COMPLETED,
    },
    ServiceRequest.Status.NEEDS_INFO: {
        ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.REJECTED,
    },
    ServiceRequest.Status.REFERRED: {
        ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.APPROVED,
        ServiceRequest.Status.REJECTED,
    },
    ServiceRequest.Status.APPROVED: {
        ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED,
    },
    ServiceRequest.Status.REJECTED: {ServiceRequest.Status.CLOSED},
    ServiceRequest.Status.COMPLETED: {ServiceRequest.Status.CLOSED},
    ServiceRequest.Status.CLOSED: set(),
}


def _may_process_request(user, item):
    if user.is_superuser or user.role in PRIVILEGED:
        return True
    if user.role != "insurance_specialist" or item.is_confidential:
        return False
    return item.assigned_to_id == user.pk or item.assigned_to_id is None


@login_required
def request_list(request):
    qs = scoped_requests_for(request.user).order_by("-created_at", "-pk")
    page_obj = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "requests_portal/request_list.html", {"requests_list": page_obj.object_list, "page_obj": page_obj})


@login_required
def request_create(request):
    allowed_roles = PRIVILEGED | {"subsidiary_rep", "employee"}
    if not request.user.is_superuser and request.user.role not in allowed_roles:
        raise PermissionDenied
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                item = form.save(commit=False)
                item.submitted_by = request.user
                item.company = request.user.company
                item.person = form.cleaned_data.get("person")
                item.reference = "IB-" + secrets.token_hex(5).upper()
                item.is_confidential = item.kind == ServiceRequest.Kind.MEDICAL_ASSISTANCE
                item.save()
                AuditEvent.objects.create(
                    actor=request.user, action="service_request_created",
                    object_type="ServiceRequest", object_id=str(item.pk),
                    summary=f"درخواست {item.reference} ثبت شد",
                )
            messages.success(request, f"درخواست شما با شماره پیگیری {item.reference} ثبت شد.")
            return redirect("request_list")
    else:
        form = ServiceRequestForm(user=request.user)
    return render(request, "requests_portal/request_form.html", {"form": form})


@login_required
def request_detail(request, pk):
    item = get_object_or_404(scoped_requests_for(request.user), pk=pk)
    if request.method == "POST":
        if not _may_process_request(request.user, item):
            raise PermissionDenied
        status = request.POST.get("status")
        if status not in dict(ServiceRequest.Status.choices):
            raise PermissionDenied
        if request.user.role == "insurance_specialist" and status in {
            ServiceRequest.Status.APPROVED, ServiceRequest.Status.REJECTED,
            ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED,
        }:
            raise PermissionDenied

        response_text = request.POST.get("response", "").strip()[:10000]
        if status in {ServiceRequest.Status.NEEDS_INFO, ServiceRequest.Status.REJECTED} and not response_text:
            messages.error(request, "برای درخواست اطلاعات تکمیلی یا رد درخواست، درج توضیح الزامی است.")
            return redirect("request_detail", pk=item.pk)

        with transaction.atomic():
            # Re-read under a row lock so concurrent updates cannot silently overwrite
            # each other's status or response.
            item = get_object_or_404(
                scoped_requests_for(request.user).select_for_update(), pk=pk
            )
            if not _may_process_request(request.user, item):
                raise PermissionDenied
            previous_status = item.status
            if status != previous_status and status not in TRANSITIONS.get(previous_status, set()):
                messages.error(request, "این تغییر وضعیت با گردش کار درخواست سازگار نیست.")
                return redirect("request_detail", pk=item.pk)

            item.status = status
            if response_text:
                stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
                actor = request.user.get_full_name() or request.user.get_username()
                entry = f"[{stamp} | {actor} | {status}]\n{response_text}"
                item.response = f"{item.response.rstrip()}\n\n{entry}".strip() if item.response else entry

            # Only the specialist who starts reviewing an unassigned, non-confidential
            # request claims it. A head/admin update must not remove it from the queue.
            if (
                request.user.role == "insurance_specialist"
                and item.assigned_to_id is None
                and status == ServiceRequest.Status.IN_REVIEW
            ):
                item.assigned_to = request.user
            item.save(update_fields=["status", "response", "assigned_to", "updated_at"])
            AuditEvent.objects.create(
                actor=request.user, action="service_request_updated",
                object_type="ServiceRequest", object_id=str(item.pk),
                summary=f"وضعیت درخواست از {previous_status} به {status} تغییر کرد",
            )
        messages.success(request, "درخواست به‌روزرسانی شد.")
        return redirect("request_detail", pk=item.pk)

    can_process = _may_process_request(request.user, item)
    allowed_statuses = [(item.status, item.get_status_display())]
    if can_process:
        next_statuses = set(TRANSITIONS.get(item.status, set()))
        if request.user.role == "insurance_specialist":
            next_statuses -= {
                ServiceRequest.Status.APPROVED,
                ServiceRequest.Status.REJECTED,
                ServiceRequest.Status.COMPLETED,
                ServiceRequest.Status.CLOSED,
            }
        allowed_statuses.extend(
            (key, label) for key, label in ServiceRequest.Status.choices
            if key in next_statuses
        )
    return render(request, "requests_portal/request_detail.html", {
        "item": item, "statuses": allowed_statuses,
        "can_process": can_process,
    })
