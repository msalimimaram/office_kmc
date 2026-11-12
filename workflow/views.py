from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Q

from accounts.access import has_global_access, is_unit_manager
from accounts.models import RoleAssignment, User
from .models import WorkflowCase, WorkflowEvent, WorkflowSatisfactionSurvey, WorkflowTransition
from .forms import WorkflowSatisfactionForm
from .presentation import build_workflow_presentation
from .services import (
    _has_any_role, _scope_for_object, acknowledge_case, mark_case_opened,
    set_final_lock, transition_case, is_delegated_assignee,
    _case_actor_authorized,
    active_position_assignments_for_level,
    _workflow_owner_candidates,
)


def _visible_cases(user):
    qs = WorkflowCase.objects.select_related(
        "definition", "current_step", "current_assignee", "content_type"
    )
    if has_global_access(user):
        return qs

    # Current and former assignees can read their own audit trail. A supervisor
    # or responsible can additionally monitor cases assigned to active internal
    # subordinates in their authorized organizational branch; this is read-only.
    # Current ownership requires a live authorization grant (checked below).
    # Historical owners retain read-only event access; event recipients alone
    # do not create an enduring permission after reassignment or expiry.
    visible = Q(current_assignee=user) | Q(events__from_assignee=user)
    if is_unit_manager(user):
        from django.contrib.auth import get_user_model
        from tasks.forms import _manager_scope

        UserModel = get_user_model()
        subordinate_ids = UserModel.objects.filter(_manager_scope(user)).values("pk")
        visible |= Q(current_assignee_id__in=subordinate_ids)
    return qs.filter(visible).distinct()


def _eligible_recipients(case, transition):
    if transition.action_code == "return_to_creator":
        started = WorkflowEvent.objects.filter(
            workflow_case=case,
            event_type=WorkflowEvent.EventType.STARTED,
        ).order_by("sent_at", "pk").first()
        return User.objects.filter(pk=started.actor_id, is_active=True) if started else User.objects.none()
    if transition.action_code in {
        "submit_information", "return_from_insurer", "return_for_correction",
        "send_back_to_insurer", "resume_review",
    }:
        previous_event = WorkflowEvent.objects.filter(
            workflow_case=case,
            to_assignee_id=case.current_assignee_id,
            from_assignee__isnull=False,
        ).order_by("-sent_at", "-pk").first()
        if previous_event and previous_event.from_assignee_id:
            return User.objects.filter(
                pk=previous_event.from_assignee_id, is_active=True
            )
        return User.objects.none()

    roles = transition.recipient_roles or (
        transition.target_step.allowed_roles if transition.target_step_id else []
    )
    position_levels = transition.recipient_position_levels or (
        transition.target_step.allowed_position_levels if transition.target_step_id else []
    )
    if not roles and not position_levels:
        return User.objects.none()

    scope = _scope_for_object(case.content_object)
    role_user_ids = set()
    if roles:
        today = timezone.localdate()
        assignments = RoleAssignment.objects.filter(
            role__in=roles,
            is_active=True,
            valid_from__lte=today,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))

        scoped_roles = Q()
        for role in roles:
            role_filter = Q(role=role)
            if role == RoleAssignment.Role.SUBSIDIARY_REP:
                if not scope["company_id"]:
                    continue
                role_filter &= Q(company_id=scope["company_id"])
                if scope["line_code"]:
                    role_filter &= Q(line_code__in=[scope["line_code"], "*"])
                else:
                    role_filter &= Q(line_code="*")
            elif role == RoleAssignment.Role.INSURER_REP:
                if not scope["insurer_id"]:
                    continue
                role_filter &= Q(insurer_id=scope["insurer_id"])
            elif role == RoleAssignment.Role.INSURANCE_SPECIALIST:
                if not scope["line_code"]:
                    continue
                role_filter &= Q(line_code__in=[scope["line_code"], "*"])
            scoped_roles |= role_filter

        if scoped_roles.children:
            role_user_ids.update(
                assignments.filter(scoped_roles).values_list("user_id", flat=True)
            )

    position_user_ids = set()
    for level in position_levels:
        position_user_ids.update(
            active_position_assignments_for_level(
                level,
                line_code=scope["line_code"],
                source_user=case.current_assignee,
                route_scope=transition.position_route_scope,
            ).values_list("user_id", flat=True)
        )

    eligible_ids = role_user_ids | position_user_ids
    if not eligible_ids:
        return User.objects.none()
    return User.objects.filter(
        is_active=True, pk__in=eligible_ids
    ).distinct().order_by("last_name", "first_name", "username")


@login_required
def workflow_case_list(request):
    cases = _visible_cases(request.user).select_related(
        "definition", "current_step", "current_assignee", "current_position_assignment",
        "delegation", "content_type",
    ).order_by("sla_due_at", "-opened_at")
    if has_global_access(request.user):
        page_obj = Paginator(cases, 25).get_page(request.GET.get("page"))
        case_rows = list(page_obj.object_list)
    else:
        # Current owners must still hold the exact role/position grant. Prior
        # owners can read only their own historical trail, never act on it.
        visible_rows = []
        for case in cases.iterator(chunk_size=200):
            if case.current_assignee_id == request.user.pk:
                scope = _scope_for_object(case.content_object)
                delegated = is_delegated_assignee(case, request.user)
                authorized = delegated or bool(
                    case.current_step
                    and _case_actor_authorized(
                        case, request.user, case.current_step.allowed_roles,
                        position_levels=case.current_step.allowed_position_levels,
                        scope=scope,
                    )
                )
                if not authorized:
                    continue
            visible_rows.append(case)
        page_obj = Paginator(visible_rows, 25).get_page(request.GET.get("page"))
        case_rows = list(page_obj.object_list)
    for case in case_rows:
        case.domain_presentation = build_workflow_presentation(case, user=request.user)
    return render(request, "workflow/workflow_case_list.html", {
        "cases": case_rows,
        "page_obj": page_obj,
    })


@login_required
def workflow_case_detail(request, pk):
    case = get_object_or_404(_visible_cases(request.user), pk=pk)
    scope = _scope_for_object(case.content_object)
    if case.current_assignee_id == request.user.pk and not (
        is_delegated_assignee(case, request.user)
        or (
            case.current_step
            and _case_actor_authorized(
                case, request.user, case.current_step.allowed_roles,
                position_levels=case.current_step.allowed_position_levels,
                scope=scope,
            )
        )
    ):
        raise PermissionDenied("انتصاب جاری شما برای مشاهده عملیاتی این پرونده معتبر نیست.")
    current_step = case.current_step
    can_act = (
        current_step is not None
        and case.current_assignee_id == request.user.pk
        and not case.is_locked
        and case.status in {WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING}
        and (
            is_delegated_assignee(case, request.user)
            or _case_actor_authorized(
                case,
                request.user,
                current_step.allowed_roles,
                position_levels=current_step.allowed_position_levels,
                scope=scope,
            )
        )
    )
    can_lock = _has_any_role(request.user, [RoleAssignment.Role.SYSTEM_ADMIN])

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "acknowledge":
                acknowledge_case(case_id=case.pk, actor=request.user, note=request.POST.get("note", "").strip())
                messages.success(request, "تأیید رسمی مشاهده ثبت شد.")
            elif action == "final_lock":
                set_final_lock(case_id=case.pk, actor=request.user, reason=request.POST.get("note", "").strip())
                messages.success(request, "قفل نهایی پرونده ثبت شد.")
            else:
                recipient_id = request.POST.get("recipient") or None
                recipient = User.objects.filter(pk=recipient_id, is_active=True).first() if recipient_id else None
                if recipient_id and not recipient:
                    raise ValidationError("گیرنده انتخاب‌شده معتبر نیست.")
                transition_case(
                    case_id=case.pk,
                    actor=request.user,
                    action_code=action,
                    recipient=recipient,
                    note=request.POST.get("note", "").strip(),
                )
                messages.success(request, "اقدام و ارجاع ثبت شد.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect("workflow_case_detail", pk=case.pk)

    if can_act:
        mark_case_opened(case_id=case.pk, actor=request.user)
        case.refresh_from_db()
    events = case.events.select_related("actor", "from_step", "to_step", "from_assignee", "to_assignee")
    domain_object = case.content_object
    is_confidential_request = bool(getattr(domain_object, "is_confidential", False))
    is_person_change = bool(
        case.content_type_id
        and case.content_type.app_label == "organizations"
        and case.content_type.model == "personchangerequest"
    )
    is_current_owner = case.current_assignee_id == request.user.pk
    if not has_global_access(request.user) and (
        is_confidential_request or (is_person_change and not is_current_owner)
    ):
        # Medical notes may contain clinical details. Historical person-change
        # recipients may see the routing trail, never free-text notes that can
        # reveal old/new identity, contact, or banking values.
        for event in events:
            event.note = ""
    presentation = build_workflow_presentation(case, user=request.user)
    transitions = []
    if can_act:
        for item in WorkflowTransition.objects.filter(
            definition=case.definition, source_step=case.current_step
        ).select_related("target_step"):
            roles = item.allowed_roles or case.current_step.allowed_roles
            position_levels = (
                item.allowed_position_levels
                or case.current_step.allowed_position_levels
            )
            if is_delegated_assignee(case, request.user) or _case_actor_authorized(
                case,
                request.user,
                roles,
                position_levels=position_levels,
                scope=scope,
            ):
                transitions.append((item, _eligible_recipients(case, item)))
    return render(request, "workflow/workflow_case_detail.html", {
        "case": case,
        "presentation": presentation,
        "events": events,
        "transitions": transitions,
        "can_act": can_act,
        "can_lock": can_lock,
    })


@login_required
def workflow_satisfaction_submit(request, pk):
    case = get_object_or_404(
        WorkflowCase.objects.select_related("definition", "content_type"),
        pk=pk,
        status__in=[WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED],
    )
    owners = _workflow_owner_candidates(case.content_object)
    if not any(owner.pk == request.user.pk for owner in owners):
        raise PermissionDenied("ثبت ارزیابی فقط برای درخواست‌کننده یا بیمه‌شده مرتبط مجاز است.")

    existing = WorkflowSatisfactionSurvey.objects.filter(
        workflow_case=case, respondent=request.user
    ).first()
    if existing:
        return render(request, "workflow/satisfaction_submitted.html", {
            "survey": existing,
        })

    form = WorkflowSatisfactionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                locked_case = WorkflowCase.objects.select_for_update().get(pk=case.pk)
                if locked_case.status not in {WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED}:
                    raise PermissionDenied("ثبت ارزیابی فقط پس از پایان گردش کار مجاز است.")
                survey = form.save(commit=False)
                survey.workflow_case = locked_case
                survey.respondent = request.user
                survey.save()
        except IntegrityError:
            return redirect("workflow_satisfaction_submitted", pk=case.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("workflow_satisfaction_submitted", pk=case.pk)

    return render(request, "workflow/satisfaction_form.html", {
        "case": case,
        "form": form,
    })


@login_required
def workflow_satisfaction_submitted(request, pk):
    case = get_object_or_404(
        WorkflowCase.objects.select_related("definition", "content_type"),
        pk=pk,
        status__in=[WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED],
    )
    survey = get_object_or_404(
        WorkflowSatisfactionSurvey,
        workflow_case=case,
        respondent=request.user,
    )
    return render(request, "workflow/satisfaction_submitted.html", {
        "survey": survey,
    })
