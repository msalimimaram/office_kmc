from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
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
    is_unit_manager,
)
from accounts.models import RoleAssignment
from claims.models import Claim
from core.permissions import scoped_claims_for, scoped_requests_for
from insurance.models import Contract
from organizations.models import Company
from requests_portal.models import ServiceRequest
from auditlog.services import record_event
from .forms import CorrespondenceForm, CorrespondenceFollowUpForm, CorrespondenceLinkForm
from .models import Correspondence, CorrespondenceEvent, CorrespondenceLink
from .services import create_correspondence, add_correspondence_event
from tasks.forms import _manager_scope
from accounts.models import User


def _scope(user):
    qs = Correspondence.objects.select_related(
        "company", "insurer", "contract", "assigned_to", "created_by"
    )
    if has_global_access(user):
        return qs

    # Explicit current assignment grants access to the assigned item even for a
    # supervisor/responsible position that is not represented by an app role.
    allowed = models.Q(assigned_to=user, is_confidential=False) | models.Q(
        created_by=user, is_confidential=False
    )
    if is_unit_manager(user):
        subordinate_ids = User.objects.filter(_manager_scope(user)).values("pk")
        allowed |= models.Q(assigned_to__in=subordinate_ids, is_confidential=False)
        allowed |= models.Q(created_by__in=subordinate_ids, is_confidential=False)

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



def _visible_link_target(user, target_type, target_id):
    if target_type == "company":
        if has_global_access(user):
            queryset = Company.objects.filter(is_active=True)
        else:
            allowed_company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            insurer_ids = insurer_ids_for(user)
            if insurer_ids:
                allowed_company_ids |= set(
                    Contract.objects.filter(insurer_id__in=insurer_ids)
                    .values_list("companies__pk", flat=True)
                )
            specialist_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
            if specialist_lines:
                contracts = Contract.objects.all()
                if "*" not in specialist_lines:
                    contracts = contracts.filter(line__in=specialist_lines)
                allowed_company_ids |= set(contracts.values_list("companies__pk", flat=True))
            queryset = Company.objects.filter(pk__in=allowed_company_ids, is_active=True)
        return queryset.filter(pk=target_id).first()

    if target_type == "contract":
        if has_global_access(user):
            queryset = Contract.objects.all()
        else:
            allowed = models.Q(pk__in=[])
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            insurer_ids = insurer_ids_for(user)
            lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
            if company_ids:
                allowed |= models.Q(companies__in=company_ids)
            if insurer_ids:
                allowed |= models.Q(insurer_id__in=insurer_ids)
            if lines:
                allowed |= models.Q(line__in=lines) if "*" not in lines else models.Q(pk__gt=0)
            queryset = Contract.objects.filter(allowed).distinct()
        return queryset.filter(pk=target_id).first()

    if target_type == "claim":
        return scoped_claims_for(user).filter(pk=target_id).first()

    if target_type == "request":
        return scoped_requests_for(user).filter(pk=target_id).first()

    return None


def _validate_correspondence_target(item, target_type, target):
    target_company_id = None
    target_insurer_id = None
    if target_type == "company":
        target_company_id = target.pk
    elif target_type == "contract":
        target_insurer_id = target.insurer_id
        company_ids = set(target.companies.values_list("pk", flat=True))
        if item.company_id and item.company_id not in company_ids:
            raise PermissionDenied("قرارداد انتخاب‌شده با شرکت مکاتبه یکسان نیست.")
    elif target_type == "claim":
        target_company_id = target.company_snapshot_id
        target_insurer_id = target.insurer_id
    elif target_type == "request":
        target_company_id = target.company_id
        if target_company_id is None and target.person_id:
            target_company_id = target.person.company_id

    if item.company_id and target_company_id and item.company_id != target_company_id:
        raise PermissionDenied("رکورد مقصد متعلق به شرکت مکاتبه نیست.")
    if item.insurer_id and target_insurer_id and item.insurer_id != target_insurer_id:
        raise PermissionDenied("رکورد مقصد متعلق به بیمه‌گر مکاتبه نیست.")


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
    allowed_create = has_global_access(request.user) or is_unit_manager(request.user) or any(
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
    allowed = has_global_access(user) or is_unit_manager(user) or any(
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
    follow_up_form = CorrespondenceFollowUpForm(initial={
        "follow_up_status": item.follow_up_status,
        "follow_up_due": item.follow_up_due,
    })
    link_form = CorrespondenceLinkForm()

    if request.method == "POST":
        if not can_manage:
            raise PermissionDenied("پس از ارجاع، اقدام فقط برای مسئول جاری یا مدیر مجاز است.")
        action = request.POST.get("action", "follow_up").strip()
        if action == "add_link":
            link_form = CorrespondenceLinkForm(request.POST)
            if link_form.is_valid():
                target_type = link_form.cleaned_data["target_type"]
                target_id = link_form.cleaned_data["target_id"]
                target = _visible_link_target(user, target_type, target_id)
                if target is None:
                    raise PermissionDenied("رکورد مقصد در محدوده دسترسی شما نیست.")
                _validate_correspondence_target(item, target_type, target)
                content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
                with transaction.atomic():
                    link, created = CorrespondenceLink.objects.get_or_create(
                        correspondence=item,
                        content_type=content_type,
                        object_id=str(target.pk),
                        defaults={"created_by": user},
                    )
                    if created:
                        record_event(
                            actor=user,
                            action="correspondence_link_created",
                            obj=item,
                            summary=f"رکورد {target_type} با شناسه {target.pk} به مکاتبه متصل شد.",
                            after_data={
                                "link_id": link.pk,
                                "target_type": target_type,
                                "target_id": target.pk,
                                "content_type_id": content_type.pk,
                            },
                            request=request,
                        )
                        messages.success(request, "رکورد با موفقیت به مکاتبه متصل شد.")
                    else:
                        messages.info(request, "این رکورد قبلاً به مکاتبه متصل شده است.")
                return redirect("correspondence_detail", pk=pk)
        elif action == "follow_up":
            follow_up_form = CorrespondenceFollowUpForm(request.POST)
            if follow_up_form.is_valid():
                with transaction.atomic():
                    locked = get_object_or_404(_scope(user).select_for_update(), pk=pk)
                    before_status = locked.follow_up_status
                    before_due = locked.follow_up_due
                    locked.follow_up_status = follow_up_form.cleaned_data["follow_up_status"]
                    locked.follow_up_due = follow_up_form.cleaned_data["follow_up_due"]
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
                        summary=follow_up_form.cleaned_data["note"],
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
            raise PermissionDenied("عملیات درخواستی برای مکاتبه معتبر نیست.")

    return render(request, "correspondence/correspondence_detail.html", {
        "item": item,
        "events": item.events.select_related("actor").all(),
        "links": item.links.select_related("content_type", "created_by").all(),
        "form": follow_up_form,
        "link_form": link_form,
        "can_manage": can_manage,
    })
