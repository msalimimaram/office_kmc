from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.text import get_valid_filename
from django.db.models import Q
from django.core.paginator import Paginator

from auditlog.models import AuditEvent
from core.permissions import PRIVILEGED
from .forms import AnnouncementForm
from .models import Announcement

STAFF_ROLES = PRIVILEGED | {"insurance_specialist"}
ROLE_AUDIENCE = {
    "system_admin": {"all", "staff"},
    "department_head": {"all", "staff"},
    "insurance_specialist": {"all", "staff"},
    "subsidiary_rep": {"all", "subsidiary"},
    "employee": {"all", "employees"},
    "insurer": {"all", "insurers"},
    "finance": {"all", "finance_legal"},
    "legal": {"all", "finance_legal"},
    "auditor": {"all", "staff"},
}


def _visible_announcements(user):
    now = timezone.now()
    qs = Announcement.objects.select_related("company", "created_by").filter(is_published=True, publish_at__lte=now).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=now)
    )
    qs = qs.filter(audience__in=ROLE_AUDIENCE.get(user.role, {"all"}))
    if user.is_superuser or user.role in STAFF_ROLES:
        return qs
    if user.company_id:
        return qs.filter(Q(company__isnull=True) | Q(company_id=user.company_id))
    return qs.filter(company__isnull=True)


@login_required
def announcement_list(request):
    page_obj = Paginator(_visible_announcements(request.user).order_by("-publish_at", "-created_at"), 20).get_page(request.GET.get("page"))
    return render(request, "announcements/announcement_list.html", {
        "announcements": page_obj.object_list, "page_obj": page_obj,
        "can_manage": request.user.is_superuser or request.user.role in STAFF_ROLES,
    })


@login_required
def announcement_create(request):
    if not (request.user.is_superuser or request.user.role in STAFF_ROLES):
        raise PermissionDenied
    if request.method == "POST":
        form = AnnouncementForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.created_by = request.user
            item.save()
            AuditEvent.objects.create(
                actor=request.user, action="announcement_created", object_type="Announcement",
                object_id=str(item.pk), summary=f"اطلاعیه ثبت شد: {item.title}",
            )
            messages.success(request, "اطلاعیه ثبت شد.")
            return redirect("announcement_list")
    else:
        form = AnnouncementForm()
    return render(request, "announcements/announcement_form.html", {"form": form})


@login_required
def announcement_download(request, pk):
    item = get_object_or_404(_visible_announcements(request.user), pk=pk)
    if not item.attachment:
        raise Http404("پیوستی برای این اطلاعیه وجود ندارد.")
    try:
        handle = item.attachment.open("rb")
    except (OSError, ValueError):
        raise Http404("فایل در دسترس نیست.")
    filename = get_valid_filename(Path(item.attachment.name).name) or f"announcement-{item.pk}"
    AuditEvent.objects.create(
        actor=request.user, action="announcement_attachment_downloaded",
        object_type="Announcement", object_id=str(item.pk), summary=f"دریافت پیوست اطلاعیه: {item.title}",
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
