from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from claims.models import Claim
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask
from core.permissions import scoped_claims_for, scoped_requests_for
from dashboard.services import insured_dashboard_metrics, management_kpis


ROLE_CAPABILITIES = {
    "system_admin": {"claims", "requests", "tasks", "assets", "contracts", "people", "correspondence", "imports", "review"},
    "department_head": {"claims", "requests", "tasks", "assets", "contracts", "people", "correspondence", "imports", "review"},
    "insurance_specialist": {"claims", "requests", "tasks", "assets", "contracts", "people", "correspondence", "imports"},
    "subsidiary_rep": {"claims", "requests", "tasks", "assets", "contracts", "people", "correspondence"},
    "employee": {"claims", "requests", "tasks", "people"},
    "insurer": {"claims", "tasks", "assets", "contracts", "correspondence", "imports"},
    "finance": {"tasks", "assets", "correspondence"},
    "legal": {"tasks", "assets", "correspondence"},
    "auditor": {"claims", "tasks", "assets", "contracts", "people", "correspondence"},
}


@login_required
def home(request):
    user = request.user
    capabilities = set(ROLE_CAPABILITIES.get(user.role, set()))
    if user.is_superuser:
        capabilities = set().union(*ROLE_CAPABILITIES.values())

    claims = scoped_claims_for(user) if "claims" in capabilities else Claim.objects.none()
    requests = scoped_requests_for(user) if "requests" in capabilities else ServiceRequest.objects.none()
    if "tasks" in capabilities:
        tasks = InternalTask.objects.filter(assignees=user) | InternalTask.objects.filter(created_by=user)
        if user.is_superuser or user.role in {"system_admin", "department_head"}:
            tasks = InternalTask.objects.all()
        tasks = tasks.distinct()
    else:
        tasks = InternalTask.objects.none()

    is_management = user.is_superuser or user.role in {"system_admin", "department_head"}
    is_employee_dashboard = user.role == "employee" and not user.is_superuser

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
        "can_review_requests": "review" in capabilities,
        "can_create_request": user.role in {"system_admin", "department_head", "subsidiary_rep", "employee"} or user.is_superuser,
        "is_employee_dashboard": is_employee_dashboard,
        "is_management": is_management,
        "management_kpis": management_kpis(user) if is_management else {},
        "insured_metrics": insured_dashboard_metrics(user) if is_employee_dashboard else {},
    }
    return render(request, "dashboard/home.html", context)
