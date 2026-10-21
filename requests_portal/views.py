import secrets
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import PermissionDenied
from .models import ServiceRequest
from .forms import ServiceRequestForm
from core.permissions import scoped_requests_for, PRIVILEGED
from auditlog.models import AuditEvent

@login_required
def request_list(request):
    qs = scoped_requests_for(request.user)
    return render(request, "requests_portal/request_list.html", {"requests_list": qs})

@login_required
def request_create(request):
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.submitted_by = request.user
            item.company = request.user.company
            item.reference = "IB-" + secrets.token_hex(5).upper()
            item.is_confidential = item.kind == ServiceRequest.Kind.MEDICAL_ASSISTANCE
            item.save()
            AuditEvent.objects.create(actor=request.user, action="service_request_created", object_type="ServiceRequest", object_id=str(item.pk), summary=f"درخواست {item.reference} ثبت شد")
            messages.success(request, f"درخواست شما با شماره پیگیری {item.reference} ثبت شد.")
            return redirect("request_list")
    else:
        form = ServiceRequestForm()
    return render(request, "requests_portal/request_form.html", {"form": form})

@login_required
def request_detail(request, pk):
    item = get_object_or_404(scoped_requests_for(request.user), pk=pk)
    if request.method == "POST":
        if request.user.role not in PRIVILEGED and not request.user.is_superuser:
            raise PermissionDenied
        status = request.POST.get("status")
        valid = dict(ServiceRequest.Status.choices)
        if status not in valid:
            raise PermissionDenied
        item.status = status
        item.response = request.POST.get("response", "")[:10000]
        item.assigned_to = request.user
        item.save()
        AuditEvent.objects.create(actor=request.user, action="service_request_updated", object_type="ServiceRequest", object_id=str(item.pk), summary=f"وضعیت درخواست به {status} تغییر کرد")
        messages.success(request, "درخواست به‌روزرسانی شد.")
        return redirect("request_detail", pk=item.pk)
    return render(request, "requests_portal/request_detail.html", {"item": item, "statuses": ServiceRequest.Status.choices})
