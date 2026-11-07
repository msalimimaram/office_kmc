from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from auditlog.services import record_event
from core.permissions import can_decide_claim, scoped_claims_for
from .forms import ClaimObjectionForm, ClaimObjectionReviewForm
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
    can_review_objections = can_decide_claim(user, claim)
    if can_review_objections:
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
        "can_review_objections": can_review_objections,
        "is_global_reviewer": has_global_access(user),
    })


@login_required
@require_POST
def claim_objection_review(request, pk, objection_pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    if not can_decide_claim(request.user, claim):
        raise PermissionDenied

    objection = get_object_or_404(
        claim.objections.select_related("submitted_by"),
        pk=objection_pk,
    )
    form = ClaimObjectionReviewForm(request.POST)
    if not form.is_valid():
        messages.error(request, "اطلاعات رسیدگی به اعتراض معتبر نیست.")
        return redirect("claim_detail", pk=claim.pk)

    target_status = form.cleaned_data["status"]
    response_text = (form.cleaned_data.get("response") or "").strip()
    allowed_transitions = {
        ClaimObjection.Status.OPEN: {ClaimObjection.Status.IN_REVIEW},
        ClaimObjection.Status.IN_REVIEW: {ClaimObjection.Status.ANSWERED},
        ClaimObjection.Status.ANSWERED: {ClaimObjection.Status.IN_REVIEW, ClaimObjection.Status.CLOSED},
        ClaimObjection.Status.CLOSED: set(),
    }
    if target_status not in allowed_transitions.get(objection.status, set()):
        raise PermissionDenied("انتقال وضعیت اعتراض از مرحله فعلی مجاز نیست.")
    if target_status == ClaimObjection.Status.CLOSED:
        if not has_global_access(request.user):
            raise PermissionDenied("بستن نهایی اعتراض فقط برای رئیس اداره یا مدیر سامانه مجاز است.")
        if not objection.response.strip():
            raise PermissionDenied("اعتراض بدون پاسخ ثبت‌شده قابل بستن نیست.")

    with transaction.atomic():
        objection = claim.objections.select_for_update().get(pk=objection.pk)
        previous_status = objection.status
        previous_response = objection.response
        if response_text:
            stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
            actor_name = request.user.get_full_name() or request.user.get_username()
            entry = f"[{stamp} | {actor_name} | {target_status}]\n{response_text}"
            objection.response = f"{objection.response.rstrip()}\n\n{entry}".strip() if objection.response else entry
        objection.status = target_status
        objection.save(update_fields=["status", "response", "updated_at"])
        record_event(
            actor=request.user,
            action="claim_objection_reviewed",
            obj=claim,
            summary=f"وضعیت اعتراض خسارت به {target_status} تغییر کرد",
            before_data={
                "objection_id": objection.pk,
                "status": previous_status,
                "response": previous_response,
            },
            after_data={
                "objection_id": objection.pk,
                "status": objection.status,
                "response": objection.response,
            },
            request=request,
        )
    messages.success(request, "وضعیت اعتراض به‌روزرسانی شد.")
    return redirect("claim_detail", pk=claim.pk)
