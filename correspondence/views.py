from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.text import get_valid_filename
from django.db.models import Q
from django.core.paginator import Paginator

from auditlog.models import AuditEvent
from core.permissions import PRIVILEGED
from .forms import CorrespondenceForm
from .models import Correspondence

STAFF_ROLES = PRIVILEGED | {"insurance_specialist", "auditor"}
CREATE_ROLES = PRIVILEGED | {"insurance_specialist"}


def _scope(user):
    qs = Correspondence.objects.select_related("company", "insurer", "contract", "assigned_to", "created_by")
    if user.is_superuser or user.role in PRIVILEGED:
        return qs
    if user.role == "insurance_specialist":
        return qs.filter(is_confidential=False)
    if user.role == "auditor":
        return qs.filter(is_confidential=False)
    if user.role == "insurer":
        return qs.filter(insurer_id=user.insurer_id, is_confidential=False) if user.insurer_id else qs.none()
    if user.role == "subsidiary_rep":
        return qs.filter(company_id=user.company_id, is_confidential=False) if user.company_id else qs.none()
    if user.role in {"finance", "legal"} and user.company_id:
        return qs.filter(company_id=user.company_id, is_confidential=False)
    return qs.none()


@login_required
def correspondence_list(request):
    items = _scope(request.user)
    query = request.GET.get("q", "").strip()[:100]
    follow_up = request.GET.get("follow_up", "").strip()
    if query:
        items = items.filter(
            Q(subject__icontains=query) | Q(summary__icontains=query) |
            Q(external_reference__icontains=query) | Q(company__name__icontains=query) |
            Q(insurer__name__icontains=query)
        )
    if follow_up in dict(Correspondence.FollowUp.choices):
        items = items.filter(follow_up_status=follow_up)
    page_obj = Paginator(items.distinct().order_by("-occurred_at", "-pk"), 25).get_page(request.GET.get("page"))
    return render(request, "correspondence/correspondence_list.html", {
        "items": page_obj.object_list, "page_obj": page_obj, "search_query": query, "selected_follow_up": follow_up,
        "follow_up_choices": Correspondence.FollowUp.choices,
        "can_create": request.user.is_superuser or request.user.role in CREATE_ROLES | {"subsidiary_rep"} or request.user.role == "insurer" and bool(request.user.insurer_id),
    })


@login_required
def correspondence_create(request):
    allowed = request.user.is_superuser or request.user.role in CREATE_ROLES | {"subsidiary_rep"} or request.user.role == "insurer" and bool(request.user.insurer_id)
    if not allowed:
        raise PermissionDenied
    if request.user.role == "subsidiary_rep" and not request.user.company_id:
        raise PermissionDenied
    if request.method == "POST":
        form = CorrespondenceForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            item = form.save(commit=False)
            item.created_by = request.user
            if request.user.role == "subsidiary_rep":
                item.company = request.user.company
                item.is_confidential = False
                item.assigned_to = None
            if request.user.role == "insurer":
                item.insurer = request.user.insurer
                item.is_confidential = False
                item.assigned_to = None
            if request.user.role == "insurance_specialist":
                item.is_confidential = False
            item.save()
            AuditEvent.objects.create(
                actor=request.user, action="correspondence_created", object_type="Correspondence",
                object_id=str(item.pk), summary=f"مکاتبه ثبت شد: {item.subject}",
            )
            messages.success(request, "مکاتبه ثبت شد.")
            return redirect("correspondence_list")
    else:
        form = CorrespondenceForm(user=request.user)
    return render(request, "correspondence/correspondence_form.html", {"form": form})


@login_required
def correspondence_download(request, pk):
    item = get_object_or_404(_scope(request.user), pk=pk)
    if not item.attachment:
        raise Http404("پیوستی برای این مکاتبه وجود ندارد.")
    try:
        handle = item.attachment.open("rb")
    except (OSError, ValueError):
        raise Http404("فایل در دسترس نیست.")
    filename = get_valid_filename(Path(item.attachment.name).name) or f"correspondence-{item.pk}"
    AuditEvent.objects.create(
        actor=request.user, action="correspondence_attachment_downloaded",
        object_type="Correspondence", object_id=str(item.pk), summary=f"دریافت پیوست مکاتبه: {item.subject}",
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
