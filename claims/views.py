from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
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
from .forms import (
    ClaimObjectionForm,
    ClaimObjectionReviewForm,
    ClaimPaymentForm,
    ClaimPaymentReversalForm,
)
from .models import Claim, ClaimObjection, ClaimPayment
from .services import record_payment, reverse_payment
from workflow.models import WorkflowCase, WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow


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



def _objection_workflow_case(objection):
    content_type = ContentType.objects.get_for_model(objection, for_concrete_model=False)
    return WorkflowCase.objects.filter(
        content_type=content_type,
        object_id=str(objection.pk),
    ).first()

def _can_manage_claim_payments(user, claim):
    line_code = claim.contract.line if claim.contract_id else "health"
    return has_global_access(user) or has_role(
        user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line_code
    )


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
        objections = list(claim.objections.select_related("submitted_by").all())
    else:
        objections = list(claim.objections.filter(submitted_by=user).select_related("submitted_by"))
    if objections:
        objection_content_type = ContentType.objects.get_for_model(
            ClaimObjection, for_concrete_model=False
        )
        workflow_cases = WorkflowCase.objects.filter(
            content_type=objection_content_type,
            object_id__in=[str(item.pk) for item in objections],
        ).select_related("current_step", "current_assignee")
        cases_by_object = {case.object_id: case for case in workflow_cases}
        for item in objections:
            item.workflow_case = cases_by_object.get(str(item.pk))

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
            try:
                with transaction.atomic():
                    objection = form.save(commit=False)
                    objection.claim = claim
                    objection.submitted_by = user
                    objection.deadline_at = deadline
                    objection.save()
                    workflow_case = None
                    definition = WorkflowDefinition.objects.filter(
                        code="claim_objection", is_active=True
                    ).order_by("-version").first()
                    if definition:
                        line_code = claim.contract.line if claim.contract_id else "health"
                        initial_assignee = resolve_initial_assignee(
                            definition=definition,
                            company_id=claim.company_snapshot_id or claim.person.company_id,
                            insurer_id=claim.insurer_id,
                            line_code=line_code,
                            owner_user_id=user.pk,
                        )
                        workflow_case = start_workflow(
                            obj=objection,
                            code="claim_objection",
                            actor=user,
                            assignee=initial_assignee,
                            note="اعتراض به خسارت ثبت و برای رسیدگی ارجاع شد.",
                        )
                    record_event(
                        actor=user,
                        action="claim_objection_created",
                        obj=claim,
                        summary="اعتراض به خسارت ثبت شد",
                        after_data={
                            "objection_id": objection.pk,
                            "deadline_at": deadline.isoformat(),
                            "workflow_case_id": workflow_case.pk if workflow_case else None,
                        },
                        request=request,
                    )
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "اعتراض شما ثبت شد.")
                return redirect("claim_detail", pk=claim.pk)
    else:
        form = ClaimObjectionForm()
    can_manage_payments = _can_manage_claim_payments(user, claim)
    payment_entries = []
    payment_form = None
    reversal_form = None
    if can_manage_payments:
        payment_entries = claim.payments.select_related(
            "recorded_by", "confirmed_by", "source_insurer", "reverses_payment"
        ).order_by("-created_at", "-pk")
        payment_form = ClaimPaymentForm(claim=claim, user=user)
        reversal_form = ClaimPaymentReversalForm(claim=claim, user=user)

    return render(request, "claims/claim_detail.html", {
        "claim": claim,
        "objections": objections,
        "form": form,
        "can_submit_objection": can_submit_objection,
        "can_review_objections": can_review_objections,
        "is_global_reviewer": has_global_access(user),
        "can_manage_payments": can_manage_payments,
        "payment_entries": payment_entries,
        "payment_form": payment_form,
        "reversal_form": reversal_form,
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
    workflow_case = _objection_workflow_case(objection)
    if workflow_case:
        return redirect("workflow_case_detail", pk=workflow_case.pk)
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



@login_required
@require_POST
def claim_payment_create(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    if not _can_manage_claim_payments(request.user, claim):
        raise PermissionDenied

    form = ClaimPaymentForm(request.POST, claim=claim, user=request.user)
    if not form.is_valid():
        messages.error(request, "اطلاعات ثبت پرداخت معتبر نیست: " + " ".join(
            str(error) for error in form.errors.values()
        ))
        return redirect("claim_detail", pk=claim.pk)

    try:
        record_payment(
            claim_id=claim.pk,
            amount=form.cleaned_data["amount"],
            paid_at=form.cleaned_data["paid_at"],
            source_reference=form.cleaned_data["source_reference"],
            source_insurer=form.cleaned_data["source_insurer"],
            actor=request.user,
            confirmed_by=form.cleaned_data["confirmed_by"],
            note=form.cleaned_data["note"],
            request=request,
        )
    except ValidationError as exc:
        messages.error(request, "ثبت پرداخت انجام نشد: " + " ".join(exc.messages))
    else:
        messages.success(request, "رویداد پرداخت با تأیید مستقل ثبت شد.")
    return redirect("claim_detail", pk=claim.pk)


@login_required
@require_POST
def claim_payment_reverse(request, pk, payment_pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    if not _can_manage_claim_payments(request.user, claim):
        raise PermissionDenied
    payment = get_object_or_404(
        claim.payments.filter(entry_type=ClaimPayment.EntryType.PAYMENT),
        pk=payment_pk,
    )
    form = ClaimPaymentReversalForm(request.POST, claim=claim, user=request.user)
    if not form.is_valid():
        messages.error(request, "اطلاعات برگشت پرداخت معتبر نیست: " + " ".join(
            str(error) for error in form.errors.values()
        ))
        return redirect("claim_detail", pk=claim.pk)

    try:
        reverse_payment(
            payment_id=payment.pk,
            amount=form.cleaned_data["amount"],
            actor=request.user,
            confirmed_by=form.cleaned_data["confirmed_by"],
            reason=form.cleaned_data["reason"],
            paid_at=form.cleaned_data["paid_at"],
            request=request,
        )
    except ValidationError as exc:
        messages.error(request, "برگشت پرداخت انجام نشد: " + " ".join(exc.messages))
    else:
        messages.success(request, "رویداد برگشت با تأیید مستقل ثبت شد.")
    return redirect("claim_detail", pk=claim.pk)
