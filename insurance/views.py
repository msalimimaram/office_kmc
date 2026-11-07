from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from accounts.access import company_ids_for, has_global_access, has_role, insurer_ids_for, line_codes_for
from accounts.models import RoleAssignment
from .models import Contract, InsuranceLine


def _contract_scope(user):
    qs = Contract.objects.select_related("insurer").prefetch_related("companies")
    if has_global_access(user):
        return qs
    allowed = Q(pk__in=[])
    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if "*" in lines:
            allowed |= Q(pk__gt=0)
        elif lines:
            allowed |= Q(line__in=lines)
    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        allowed |= Q(companies__in=company_ids)
    insurer_ids = insurer_ids_for(user)
    if insurer_ids:
        allowed |= Q(insurer_id__in=insurer_ids)
    return qs.filter(allowed).distinct()


@login_required
def contract_list(request):
    contracts = _contract_scope(request.user)
    if not contracts.exists():
        can_access_module = has_global_access(request.user) or has_role(
            request.user,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            RoleAssignment.Role.SUBSIDIARY_REP,
            RoleAssignment.Role.INSURER_REP,
        )
        if not can_access_module:
            raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    line = request.GET.get("line", "").strip()
    state = request.GET.get("state", "").strip()
    if query:
        contracts = contracts.filter(
            Q(code__icontains=query) | Q(title__icontains=query) | Q(insurer__name__icontains=query)
        )
    if line in dict(InsuranceLine.choices):
        if has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST):
            lines = line_codes_for(request.user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
            if "*" not in lines and line not in lines:
                raise PermissionDenied("این رشته بیمه‌ای در انتصاب شما تعریف نشده است.")
        contracts = contracts.filter(line=line)
    if state == "active":
        contracts = contracts.filter(is_active=True)
    elif state == "inactive":
        contracts = contracts.filter(is_active=False)
    page_obj = Paginator(contracts.distinct().order_by("-start_date", "code", "pk"), 25).get_page(request.GET.get("page"))
    return render(request, "insurance/contract_list.html", {
        "contracts": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
        "selected_line": line,
        "lines": InsuranceLine.choices,
        "selected_state": state,
    })
