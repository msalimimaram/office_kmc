from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.text import get_valid_filename

from accounts.access import company_ids_for, has_global_access, has_role, insurer_ids_for, is_insurance_staff
from accounts.models import RoleAssignment
from auditlog.models import AuditEvent
from .forms import AnnouncementForm
from .models import Announcement


def _visible_announcements(user):
    now = timezone.now()
    qs = Announcement.objects.select_related("company", "created_by").filter(
        is_published=True, publish_at__lte=now,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))

    if is_insurance_staff(user):
        return qs

    audiences = {Announcement.Audience.ALL}
    allowed_company_ids = set()
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        audiences.add(Announcement.Audience.SUBSIDIARY)
        allowed_company_ids |= company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        audiences.add(Announcement.Audience.EMPLOYEES)
        allowed_company_ids |= company_ids_for(user, role=RoleAssignment.Role.INSURED_PERSON)
    if has_role(user, RoleAssignment.Role.INSURER_REP):
        audiences.add(Announcement.Audience.INSURERS)

    scoped = Q(company__isnull=True)
    if allowed_company_ids:
        scoped |= Q(company_id__in=allowed_company_ids)
    return qs.filter(audience__in=audiences).filter(scoped).distinct()


@login_required
def announcement_list(request):
    page_obj = Paginator(
        _visible_announcements(request.user).order_by("-publish_at", "-created_at"), 20
    ).get_page(request.GET.get("page"))
    can_manage = is_insurance_staff(request.user)
    return render(request, "announcements/announcement_list.html", {
        "announcements": page_obj.object_list,
        "page_obj": page_obj,
        "can_manage": can_manage,
    })


@login_required
def announcement_create(request):
    if not is_insurance_staff(request.user):
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
        object_type="Announcement", object_id=str(item.pk),
        summary=f"دریافت پیوست اطلاعیه: {item.title}",
    )
    return FileResponse(handle, as_attachment=True, filename=filename)
