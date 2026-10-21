from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from .models import Contract
from core.permissions import PRIVILEGED


@login_required
def contract_list(request):
    user = request.user
    if user.is_superuser or user.role in PRIVILEGED | {"insurance_specialist", "auditor"}:
        contracts = Contract.objects.select_related("insurer").prefetch_related("companies")
    elif user.role == "subsidiary_rep" and user.company_id:
        contracts = Contract.objects.filter(companies=user.company).select_related("insurer").distinct()
    else:
        raise PermissionDenied
    return render(request, "insurance/contract_list.html", {"contracts": contracts})
