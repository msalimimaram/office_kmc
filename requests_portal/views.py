import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .models import ServiceRequest
from .forms import ServiceRequestForm
from core.permissions import scoped_requests_for, PRIVILEGED
from auditlog.models import AuditEvent


# Explicit transitions prevent requests from jumping between unrelated states.
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
    allowed_roles = PRIVILEGED | {"insurance_specialist", "subsidiary_rep", "employee"}
    if not request.user.is_superuser and request.user.role not in allowed_roles:
        raise PermissionDenied
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            item = form.save(commit=False)
            item.submitted_by = request.user
            item.company = request.user.company
            item.person = form.cleaned_data.get("person")
            item.reference = "IB-" + secrets.token_hex(5).upper()
            # Medical-assistance requests are confidential by default. The
            # requester cannot turn off confidentiality through form fields.
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
        # Final decisions are reserved for the department head and system admin,
        # regardless of whether the requested transition would otherwise be valid.
        if request.user.role == "insurance_specialist" and status in {
            ServiceRequest.Status.APPROVED, ServiceRequest.Status.REJECTED,
            ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED,
        }:
            raise PermissionDenied
        if status != item.status and status not in TRANSITIONS.get(item.status, set()):
            messages.error(request, "این تغییر وضعیت با گردش کار درخواست سازگار نیست.")
            return redirect("request_detail", pk=item.pk)
        previous_status = item.status
        item.status = status
        item.response = request.POST.get("response", "").strip()[:10000]
        if item.assigned_to_id is None:
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
