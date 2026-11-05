from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from auditlog.services import record_event
from core.permissions import scoped_claims_for
from .forms import ClaimObjectionForm
from .models import Claim


@login_required
def claim_list(request):
    claims = scoped_claims_for(request.user)
    query = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "").strip()
    if query:
        claims = claims.filter(
            Q(claim_number__icontains=query)
            | Q(person__first_name__icontains=query)
            | Q(person__last_name__icontains=query)
            | Q(service_type__icontains=query)
        )
    if status in dict(Claim.Status.choices):
        claims = claims.filter(status=status)
    page_obj = Paginator(
        claims.order_by("-registered_date", "-pk"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "claims/claim_list.html", {
        "claims": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
        "selected_status": status,
        "statuses": Claim.Status.choices,
    })


@login_required
def claim_detail(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    user = request.user
    can_submit_objection = (
        has_role(user, RoleAssignment.Role.INSURED_PERSON)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP, company_id=claim.company_snapshot_id or claim.person.company_id)
    )
    if has_global_access(user):
        objections = claim.objections.select_related("submitted_by").all()
    else:
        objections = claim.objections.filter(submitted_by=user).select_related("submitted_by")

    if request.method == "POST":
        if not can_submit_objection:
            raise PermissionDenied
        if not claim.result_sent_at:
            raise PermissionDenied("مهلت اعتراض هنوز با ارسال نتیجه آغاز نشده است.")
        deadline = claim.result_sent_at + timedelta(days=60)
        if timezone.now() > deadline:
            raise PermissionDenied("مهلت ۶۰ روزه ثبت اعتراض به پایان رسیده است.")
        form = ClaimObjectionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                objection = form.save(commit=False)
                objection.claim = claim
                objection.submitted_by = user
                objection.deadline_at = deadline
                objection.save()
                record_event(
                    actor=user,
                    action="claim_objection_created",
                    obj=claim,
                    summary="اعتراض به خسارت ثبت شد",
                    after_data={"objection_id": objection.pk, "deadline_at": deadline.isoformat()},
                    request=request,
                )
            messages.success(request, "اعتراض شما ثبت شد.")
            return redirect("claim_detail", pk=claim.pk)
    else:
        form = ClaimObjectionForm()
    return render(request, "claims/claim_detail.html", {
        "claim": claim,
        "objections": objections,
        "form": form,
        "can_submit_objection": can_submit_objection,
    })
