from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from claims.models import Claim
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask
from core.permissions import scoped_claims_for, scoped_requests_for
from dashboard.services import insured_dashboard_metrics, management_kpis, personnel_performance_metrics
from django.utils import timezone
from workflow.models import WorkflowCase


def _capabilities_for(user):
    capabilities = set()
    if has_global_access(user):
        return {
            "claims", "requests", "tasks", "assets", "contracts", "people",
            "correspondence", "imports", "review", "reports", "admin_settings",
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
    return capabilities


@login_required
def home(request):
    user = request.user
    capabilities = _capabilities_for(user)

    claims = scoped_claims_for(user) if "claims" in capabilities else Claim.objects.none()
    requests = scoped_requests_for(user) if "requests" in capabilities else ServiceRequest.objects.none()
    if "tasks" in capabilities:
        tasks = InternalTask.objects.filter(assignees=user) | InternalTask.objects.filter(created_by=user)
        if has_global_access(user):
            tasks = InternalTask.objects.all()
        else:
            # Keep dashboard counts consistent with task_list: confidential
            # request-linked tasks must never be exposed to non-global users.
            tasks = tasks.exclude(related_request__is_confidential=True)
        tasks = tasks.distinct()
    else:
        tasks = InternalTask.objects.none()

    is_management = has_global_access(user)
    is_insured_dashboard = has_role(user, RoleAssignment.Role.INSURED_PERSON) and not is_management

    context = {
        "claim_count": claims.count(),
        "request_count": requests.count(),
        "open_request_count": requests.exclude(status__in=["closed", "completed", "rejected"]).count(),
        "task_count": tasks.exclude(status__in=["done", "cancelled"]).count(),
        "recent_claims": claims.select_related("person").order_by("-registered_date", "-pk")[:8],
        "recent_requests": requests.select_related("person", "submitted_by").order_by("-created_at", "-pk")[:8],
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
        "delegated_work_cases": WorkflowCase.objects.filter(
            current_assignee=user,
            delegation__isnull=False,
            status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        ).select_related("definition", "current_step", "delegation")[:5],
        "delegated_work_count": WorkflowCase.objects.filter(
            current_assignee=user,
            delegation__isnull=False,
            status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        ).count(),
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
