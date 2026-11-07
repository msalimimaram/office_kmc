from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils.text import get_valid_filename
from django.db import models
from django.db import transaction
from django.core.paginator import Paginator

from accounts.access import (
    company_ids_for,
    has_global_access,
    has_role,
    insurer_ids_for,
    line_codes_for,
)
from accounts.models import RoleAssignment
from auditlog.services import record_event
from .forms import CorrespondenceForm, CorrespondenceFollowUpForm
from .models import Correspondence, CorrespondenceEvent
from .services import create_correspondence, add_correspondence_event


def _scope(user):
    qs = Correspondence.objects.select_related(
        "company", "insurer", "contract", "assigned_to", "created_by"
    )
    if has_global_access(user):
        return qs

    allowed = models.Q(pk__in=[])

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if "*" in lines:
            allowed |= models.Q(pk__gt=0, is_confidential=False)
        else:
            allowed |= models.Q(contract__line__in=lines, is_confidential=False)
        allowed |= models.Q(assigned_to=user, is_confidential=False)

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        allowed |= models.Q(company_id__in=company_ids, is_confidential=False)

    insurer_ids = insurer_ids_for(user)
    if insurer_ids:
        allowed |= models.Q(insurer_id__in=insurer_ids, is_confidential=False)

    return qs.filter(allowed).distinct()


def _active_company_id(request, user):
    ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    selected = request.session.get("active_company_id")
    try:
        selected_id = int(selected) if selected is not None else None
    except (TypeError, ValueError):
        selected_id = None
    if selected_id and selected_id in ids:
        return selected_id
    if len(ids) == 1:
        return next(iter(ids))
    return None


@login_required
def correspondence_list(request):
    items = _scope(request.user)
    query = request.GET.get("q", "").strip()[:100]
    follow_up = request.GET.get("follow_up", "").strip()
    if query:
        items = items.filter(
            models.Q(internal_number__icontains=query)
            | models.Q(subject__icontains=query)
            | models.Q(summary__icontains=query)
            | models.Q(external_reference__icontains=query)
            | models.Q(company__name__icontains=query)
            | models.Q(insurer__name__icontains=query)
        )
    if follow_up in dict(Correspondence.FollowUp.choices):
        items = items.filter(follow_up_status=follow_up)
    page_obj = Paginator(
        items.distinct().order_by("-occurred_at", "-pk"), 25
    ).get_page(request.GET.get("page"))
    allowed_create = has_global_access(request.user) or any(
        has_role(request.user, role)
        for role in (
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            RoleAssignment.Role.SUBSIDIARY_REP,
            RoleAssignment.Role.INSURER_REP,
        )
    )
    return render(request, "correspondence/correspondence_list.html", {
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
        "selected_follow_up": follow_up,
        "follow_up_choices": Correspondence.FollowUp.choices,
        "can_create": allowed_create,
    })


@login_required
def correspondence_create(request):
    user = request.user
    allowed = has_global_access(user) or any(
        has_role(user, role)
        for role in (
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            RoleAssignment.Role.SUBSIDIARY_REP,
            RoleAssignment.Role.INSURER_REP,
        )
    )
    if not allowed:
        raise PermissionDenied

    active_company = None
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        active_company = _active_company_id(request, user)
        if not active_company:
            raise PermissionDenied("شرکت فعال را انتخاب کنید.")
    insurer_ids = insurer_ids_for(user)
    if has_role(user, RoleAssignment.Role.INSURER_REP) and len(insurer_ids) != 1:
        raise PermissionDenied("حساب نماینده بیمه‌گر باید دقیقاً به یک بیمه‌گر متصل باشد.")

    if request.method == "POST":
        form = CorrespondenceForm(
            request.POST,
            request.FILES,
            user=user,
            active_company_id=active_company,
        )
        if form.is_valid():
            item = form.save(commit=False)
            if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
                from organizations.models import Company
                item.company = Company.objects.get(pk=active_company)
                item.is_confidential = False
            if has_role(user, RoleAssignment.Role.INSURER_REP):
                from insurance.models import Insurer
                item.insurer = Insurer.objects.get(pk=next(iter(insurer_ids)))
                item.is_confidential = False
                item.assigned_to = None
            if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST) and not has_global_access(user):
                item.is_confidential = False
            # Rebuild the form with the final server-owned scopes and use the
            # transactional numbering service; internal_number is never client-controlled.
            item.internal_number = ""
            form.instance = item
            try:
                item = create_correspondence(form=form, actor=user, request=request)
            except Exception:
                raise
            messages.success(request, f"مکاتبه با شماره {item.internal_number} ثبت شد.")
            return redirect("correspondence_list")
    else:
        form = CorrespondenceForm(
            user=user,
            active_company_id=active_company,
        )
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
    record_event(
        actor=request.user,
        action="correspondence_attachment_downloaded",
        obj=item,
        summary=f"دریافت پیوست مکاتبه: {item.internal_number}",
        request=request,
    )
    add_correspondence_event(
        correspondence=item,
        actor=request.user,
        event_type=CorrespondenceEvent.EventType.ATTACHMENT_DOWNLOADED,
        summary="پیوست مکاتبه دریافت شد.",
        metadata={"action": "download"},
        request=request,
    )
    return FileResponse(handle, as_attachment=True, filename=filename)



@login_required
def correspondence_detail(request, pk):
    user = request.user
    item = get_object_or_404(_scope(user), pk=pk)
    can_manage = (
        has_global_access(user)
        or item.assigned_to_id == user.pk
        or (item.assigned_to_id is None and item.created_by_id == user.pk)
    )
    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied("پس از ارجاع، اقدام فقط برای مسئول جاری یا مدیر مجاز است.")
        form = CorrespondenceFollowUpForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                locked = get_object_or_404(_scope(user).select_for_update(), pk=pk)
                before_status = locked.follow_up_status
                before_due = locked.follow_up_due
                locked.follow_up_status = form.cleaned_data["follow_up_status"]
                locked.follow_up_due = form.cleaned_data["follow_up_due"]
                locked.save(update_fields=["follow_up_status", "follow_up_due", "updated_at"])
                event_type = (
                    CorrespondenceEvent.EventType.STATUS_CHANGED
                    if before_status != locked.follow_up_status
                    else CorrespondenceEvent.EventType.FOLLOW_UP
                )
                add_correspondence_event(
                    correspondence=locked,
                    actor=user,
                    event_type=event_type,
                    summary=form.cleaned_data["note"],
                    metadata={
                        "previous_status": before_status,
                        "status": locked.follow_up_status,
                        "previous_due": before_due.isoformat() if before_due else None,
                        "follow_up_due": locked.follow_up_due.isoformat() if locked.follow_up_due else None,
                    },
                    request=request,
                )
            messages.success(request, "پیگیری مکاتبه ثبت شد.")
            return redirect("correspondence_detail", pk=pk)
    else:
        form = CorrespondenceFollowUpForm(initial={
            "follow_up_status": item.follow_up_status,
            "follow_up_due": item.follow_up_due,
        })

    return render(request, "correspondence/correspondence_detail.html", {
        "item": item,
        "events": item.events.select_related("actor").all(),
        "form": form,
        "can_manage": can_manage,
    })
