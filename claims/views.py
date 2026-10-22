from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.core.paginator import Paginator

from .models import Claim, ClaimObjection
from .forms import ClaimObjectionForm
from core.permissions import scoped_claims_for
from auditlog.models import AuditEvent


@login_required
def claim_list(request):
    claims = scoped_claims_for(request.user)
    query = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "").strip()
    if query:
        claims = claims.filter(
            Q(claim_number__icontains=query) |
            Q(person__first_name__icontains=query) |
            Q(person__last_name__icontains=query) |
            Q(service_type__icontains=query)
        )
    if status in dict(Claim.Status.choices):
        claims = claims.filter(status=status)
    page_obj = Paginator(claims.order_by("-registered_date", "-pk"), 25).get_page(request.GET.get("page"))
    return render(request, "claims/claim_list.html", {
        "claims": page_obj.object_list, "page_obj": page_obj,
        "search_query": query, "selected_status": status,
        "statuses": Claim.Status.choices,
    })


@login_required
def claim_detail(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    objections = claim.objections.all()
    if request.method == "POST":
        form = ClaimObjectionForm(request.POST)
        if form.is_valid():
            objection = form.save(commit=False)
            objection.claim = claim
            objection.submitted_by = request.user
            objection.save()
            AuditEvent.objects.create(
                actor=request.user, action="claim_objection_created", object_type="Claim",
                object_id=str(claim.pk), summary="اعتراض به خسارت ثبت شد",
            )
            messages.success(request, "اعتراض شما ثبت شد.")
            return redirect("claim_detail", pk=claim.pk)
    else:
        form = ClaimObjectionForm()
    return render(request, "claims/claim_detail.html", {
        "claim": claim, "objections": objections, "form": form,
    })
