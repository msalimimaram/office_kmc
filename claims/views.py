from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import PermissionDenied
from .models import Claim, ClaimObjection
from .forms import ClaimObjectionForm
from core.permissions import scoped_claims_for
from auditlog.models import AuditEvent

@login_required
def claim_list(request):
    claims = scoped_claims_for(request.user)
    return render(request, "claims/claim_list.html", {"claims": claims})

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
            AuditEvent.objects.create(actor=request.user, action="claim_objection_created", object_type="Claim", object_id=str(claim.pk), summary="اعتراض به خسارت ثبت شد")
            messages.success(request, "اعتراض شما ثبت شد.")
            return redirect("claim_detail", pk=claim.pk)
    else:
        form = ClaimObjectionForm()
    return render(request, "claims/claim_detail.html", {"claim": claim, "objections": objections, "form": form})
