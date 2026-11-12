from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from accounts.access import has_global_access, has_role, is_unit_manager
from accounts.models import RoleAssignment
from claims.models import Claim
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask
from core.permissions import scoped_claims_for, scoped_requests_for
from dashboard.services import insured_dashboard_metrics, management_kpis, personnel_performance_metrics
from django.utils import timezone
from workflow.models import WorkflowCase
from workflow.presentation import build_workflow_presentation
from workflow.services import (
    _case_actor_authorized,
    _scope_for_object,
    is_delegated_assignee,
)


def _capabilities_for(user):
    capabilities = set()
    if has_role(user, RoleAssignment.Role.SYSTEM_ADMIN):
        return {
            "claims", "requests", "tasks", "assets", "contracts", "people",
            "correspondence", "imports", "review", "reports", "admin_settings",
        }
    if has_role(user, RoleAssignment.Role.DEPARTMENT_HEAD):
        return {
            "claims", "requests", "tasks", "assets", "contracts", "people",
            "correspondence", "imports", "review", "reports",
        }

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        capabilities.update({
            "claims", "requests", "tasks", "assets", "contracts", "people",
            "correspondence", "imports", "reports",
        })
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        capabilities.update({
            "claims", "requests", "people", "contracts", "assets",
            "correspondence", "reports",
        })
    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        capabilities.update({"claims", "requests", "people"})
    if has_role(user, RoleAssignment.Role.INSURER_REP):
        capabilities.update({
            "claims", "requests", "assets", "contracts", "correspondence",
            "imports", "reports",
        })
    if is_unit_manager(user):
        capabilities.update({"tasks", "correspondence"})
    return capabilities


@login_required
def home(request):
    user = request.user
    capabilities = _capabilities_for(user)

    claims = scoped_claims_for(user) if "claims" in capabilities else Claim.objects.none()
    requests = scoped_requests_for(user) if "requests" in capabilities else ServiceRequest.objects.none()
    if "tasks" in capabilities:
        from tasks.views import _visible_tasks
        tasks = _visible_tasks(user)
    else:
        tasks = InternalTask.objects.none()

    is_system_admin = has_role(user, RoleAssignment.Role.SYSTEM_ADMIN)
    is_department_head = has_role(user, RoleAssignment.Role.DEPARTMENT_HEAD)
    is_management = has_global_access(user)
    is_insured_dashboard = has_role(user, RoleAssignment.Role.INSURED_PERSON) and not is_management
    delegated_cases = WorkflowCase.objects.filter(
        current_assignee=user,
        delegation__status="active",
        delegation__valid_from__lte=timezone.localdate(),
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
    ).filter(
        Q(delegation__valid_until__isnull=True)
        | Q(delegation__valid_until__gte=timezone.localdate())
    ).select_related("definition", "current_step", "delegation").order_by(
        "sla_due_at", "opened_at"
    )
    # Fail closed for cases whose delegation scope is ambiguous or no longer
    # authorizes this recipient. Such cases require managerial reconciliation.
    delegated_case_rows = [
        case for case in delegated_cases
        if is_delegated_assignee(case, user)
    ]

    active_statuses = [WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING]
    assigned_candidates = WorkflowCase.objects.filter(
        current_assignee=user,
        status__in=active_statuses,
        is_locked=False,
    ).select_related(
        "definition", "current_step", "current_assignee",
        "current_position_assignment", "delegation", "content_type",
    ).order_by("sla_due_at", "opened_at")[:500]
    assigned_rows = []
    for case in assigned_candidates:
        authorized = (
            is_delegated_assignee(case, user)
            if case.delegation_id
            else bool(
                case.current_step
                and _case_actor_authorized(
                    case,
                    user,
                    case.current_step.allowed_roles,
                    position_levels=case.current_step.allowed_position_levels,
                    scope=_scope_for_object(case.content_object),
                )
            )
        )
        if authorized:
            case.domain_presentation = build_workflow_presentation(case, user=user)
            assigned_rows.append(case)

    unit_workflow_rows = []
    if is_unit_manager(user) and not is_management:
        from django.contrib.auth import get_user_model
        from tasks.forms import _manager_scope

        UserModel = get_user_model()
        subordinate_ids = UserModel.objects.filter(_manager_scope(user)).values("pk")
        subordinate_cases = WorkflowCase.objects.filter(
            current_assignee_id__in=subordinate_ids,
            status__in=active_statuses,
            is_locked=False,
        ).select_related(
            "definition", "current_step", "current_assignee",
            "current_position_assignment", "delegation", "content_type",
        ).order_by("sla_due_at", "opened_at")[:100]
        for case in subordinate_cases:
            case.domain_presentation = build_workflow_presentation(case, user=user)
            unit_workflow_rows.append(case)

    oversight_workflow_count = (
        WorkflowCase.objects.filter(status__in=active_statuses, is_locked=False).count()
        if is_management else 0
    )
    oversight_overdue_count = (
        WorkflowCase.objects.filter(
            status__in=active_statuses,
            is_locked=False,
            sla_due_at__lt=timezone.now(),
        ).count()
        if is_management else 0
    )

    context = {
        "claim_count": claims.count(),
        "request_count": requests.count(),
        "open_request_count": requests.exclude(status__in=["closed", "completed", "rejected"]).count(),
        "task_count": tasks.exclude(status__in=["done", "cancelled"]).count(),
        "recent_claims": claims.select_related("person").order_by("-registered_date", "-pk")[:8],
        "recent_requests": requests.select_related("person", "submitted_by").order_by("-created_at", "-pk")[:8],
        "recent_tasks": tasks.select_related("created_by").order_by("due_at", "-pk")[:8],
        "is_unit_manager": is_unit_manager(user),
        "is_system_admin": is_system_admin,
        "is_department_head": is_department_head and not is_system_admin,
        "position_titles": list(
            user.position_assignments.filter(
                is_active=True,
                valid_from__lte=timezone.localdate(),
                unit__company__isnull=True,
                line_code__gt="",
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())
            ).values_list("position__title", flat=True).distinct()
        ),
        "capabilities": capabilities,
        "show_claims": "claims" in capabilities,
        "show_requests": "requests" in capabilities,
        "show_tasks": "tasks" in capabilities,
        "show_assets": "assets" in capabilities,
        "show_contracts": "contracts" in capabilities,
        "show_people": "people" in capabilities,
        "show_correspondence": "correspondence" in capabilities,
        "show_imports": "imports" in capabilities,
        "can_review_requests": is_management,
        "can_create_request": any(
            has_role(user, role) for role in (
                RoleAssignment.Role.SYSTEM_ADMIN,
                RoleAssignment.Role.DEPARTMENT_HEAD,
                RoleAssignment.Role.SUBSIDIARY_REP,
                RoleAssignment.Role.INSURED_PERSON,
            )
        ),
        "is_employee_dashboard": is_insured_dashboard,
        "is_management": is_management,
        "management_kpis": management_kpis(user) if is_management else {},
        "insured_metrics": insured_dashboard_metrics(user) if is_insured_dashboard else {},
        "delegated_work_cases": delegated_case_rows[:5],
        "delegated_work_count": len(delegated_case_rows),
        "workflow_action_cases": assigned_rows[:8],
        "workflow_action_count": len(assigned_rows),
        "workflow_overdue_count": sum(
            1 for case in assigned_rows if case.sla_due_at and case.sla_due_at < timezone.now()
        ),
        "unit_workflow_cases": unit_workflow_rows[:8],
        "unit_workflow_count": len(unit_workflow_rows),
        "oversight_workflow_count": oversight_workflow_count,
        "oversight_overdue_count": oversight_overdue_count,
    }
    return render(request, "dashboard/home.html", context)



@login_required
def staff_performance_report(request):
    if not has_global_access(request.user):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    from datetime import timedelta
    from django.utils.dateparse import parse_date

    today = timezone.localdate()
    end_date = parse_date(request.GET.get("end", "")) or today
    start_date = parse_date(request.GET.get("start", "")) or (end_date - timedelta(days=30))
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    rows = personnel_performance_metrics(
        request.user, start_date=start_date, end_date=end_date
    )
    return render(request, "dashboard/performance_report.html", {
        "rows": rows,
        "start_date": start_date,
        "end_date": end_date,
    })
