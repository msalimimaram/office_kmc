from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.db.models import Q

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment, User
from .models import WorkflowCase, WorkflowEvent, WorkflowTransition
from .services import acknowledge_case, mark_case_opened, set_final_lock, transition_case


def _visible_cases(user):
    qs = WorkflowCase.objects.select_related(
        "definition", "current_step", "current_assignee", "content_type"
    )
    if has_global_access(user):
        return qs
    return qs.filter(current_assignee=user)


def _eligible_recipients(transition):
    roles = transition.recipient_roles or (
        transition.target_step.allowed_roles if transition.target_step_id else []
    )
    if not roles:
        return User.objects.none()
    if "*" in roles:
        return User.objects.filter(is_active=True).order_by("last_name", "first_name", "username")
    today = timezone.localdate()
    assignments = RoleAssignment.objects.filter(
        role__in=roles,
        is_active=True,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    return User.objects.filter(is_active=True, role_assignments__in=assignments).distinct().order_by(
        "last_name", "first_name", "username"
    )


@login_required
def workflow_case_list(request):
    cases = _visible_cases(request.user).order_by("sla_due_at", "-opened_at")
    page_obj = Paginator(cases, 25).get_page(request.GET.get("page"))
    return render(request, "workflow/workflow_case_list.html", {
        "cases": page_obj.object_list,
        "page_obj": page_obj,
    })


@login_required
def workflow_case_detail(request, pk):
    case = get_object_or_404(_visible_cases(request.user), pk=pk)
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

    mark_case_opened(case_id=case.pk, actor=request.user)
    case.refresh_from_db()
    events = case.events.select_related("actor", "from_step", "to_step", "from_assignee", "to_assignee")
    transitions = []
    if has_global_access(request.user) or case.current_assignee_id == request.user.pk:
        for item in WorkflowTransition.objects.filter(
            definition=case.definition, source_step=case.current_step
        ).select_related("target_step"):
            roles = item.allowed_roles or case.current_step.allowed_roles
            if has_global_access(request.user) or "*" in roles or any(has_role(request.user, role) for role in roles):
                transitions.append((item, _eligible_recipients(item)))
    return render(request, "workflow/workflow_case_detail.html", {
        "case": case,
        "events": events,
        "transitions": transitions,
    })
