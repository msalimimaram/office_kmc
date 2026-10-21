from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.db.models import Q
from .models import InsuranceLine

from .models import Contract
from core.permissions import PRIVILEGED


@login_required
def contract_list(request):
    user = request.user
    if user.is_superuser or user.role in PRIVILEGED | {"insurance_specialist", "auditor"}:
        contracts = Contract.objects.select_related("insurer").prefetch_related("companies")
    elif user.role == "subsidiary_rep" and user.company_id:
        contracts = Contract.objects.filter(companies=user.company).select_related("insurer").distinct()
    elif user.role == "insurer" and user.insurer_id:
        contracts = Contract.objects.filter(insurer_id=user.insurer_id).select_related("insurer").prefetch_related("companies")
    else:
        raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    line = request.GET.get("line", "").strip()
    state = request.GET.get("state", "").strip()
    if query:
        contracts = contracts.filter(
            Q(code__icontains=query) | Q(title__icontains=query) | Q(insurer__name__icontains=query)
        )
    if line in dict(InsuranceLine.choices):
        contracts = contracts.filter(line=line)
    if state == "active":
        contracts = contracts.filter(is_active=True)
    elif state == "inactive":
        contracts = contracts.filter(is_active=False)
    return render(request, "insurance/contract_list.html", {
        "contracts": contracts.distinct(), "search_query": query, "selected_line": line,
        "lines": InsuranceLine.choices, "selected_state": state,
    })
