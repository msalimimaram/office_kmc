from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment, UserNotification
from auditlog.services import record_event
from core.permissions import can_decide_claim, scoped_claims_for
from .forms import (
    ClaimForm,
    ClaimAssessmentForm,
    ClaimDuplicateDeclarationForm,
    company_for_person_on_date,
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
        "can_create": has_global_access(request.user) or has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST),
    })


def _claim_workflow_case(claim):
    content_type = ContentType.objects.get_for_model(claim, for_concrete_model=False)
    return WorkflowCase.objects.filter(
        content_type=content_type,
        object_id=str(claim.pk),
    ).select_related("current_step", "current_assignee").first()



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
    can_declare_duplicate = bool(
        claim.insurer_id
        and claim.contract_id
        and claim.source_duplicate_status == Claim.DuplicateStatus.NOT_DECLARED
        and has_role(
            user,
            RoleAssignment.Role.INSURER_REP,
            insurer_id=claim.insurer_id,
            line_code=claim.contract.line,
        )
    )
    workflow_case = _claim_workflow_case(claim)
    can_assess = bool(
        workflow_case
        and workflow_case.current_step
        and workflow_case.current_step.code in {"under_review", "needs_info"}
        and (workflow_case.current_assignee_id == user.pk or has_global_access(user))
        and can_decide_claim(user, claim)
    )
    can_send_result = bool(
        claim.status in {Claim.Status.APPROVED, Claim.Status.REJECTED}
        and not claim.result_sent_at
        and can_decide_claim(user, claim)
        and workflow_case
        and workflow_case.status == WorkflowCase.Status.CLOSED
    )
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
                        initial_assignee, delegation = resolve_initial_assignee(
                            definition=definition,
                            obj=objection,
                            return_delegation=True,
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
                            delegation=delegation,
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
        "workflow_case": workflow_case,
        "can_assess": can_assess,
        "assessment_form": ClaimAssessmentForm(claim=claim) if can_assess else None,
        "can_send_result": can_send_result,
        "can_declare_duplicate": can_declare_duplicate,
        "duplicate_form": ClaimDuplicateDeclarationForm() if can_declare_duplicate else None,
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


@login_required
def claim_create(request):
    if not (
        has_global_access(request.user)
        or has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST)
    ):
        raise PermissionDenied
    form = ClaimForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                claim = form.save(commit=False)
                contract = claim.contract
                company = company_for_person_on_date(claim.person, claim.service_date)
                if not company:
                    raise ValidationError("شرکت شخص در تاریخ خدمت از سوابق اشتغال قابل تعیین نیست.")
                claim.company_snapshot = company
                claim.insurer = contract.insurer
                claim.contract_number_snapshot = contract.code
                claim.status = Claim.Status.REGISTERED
                claim.save()

                definition = WorkflowDefinition.objects.filter(
                    code="claim_review",
                    is_active=True,
                ).order_by("-version").first()
                if not definition:
                    raise ValidationError(
                        "گردش‌کار فعال claim_review برای ارزیابی خسارت پیکربندی نشده است."
                    )
                assignee, delegation = resolve_initial_assignee(
                    definition=definition,
                    obj=claim,
                    return_delegation=True,
                    company_id=company.pk,
                    insurer_id=contract.insurer_id,
                    line_code=contract.line,
                    owner_user_id=request.user.pk,
                )
                case = start_workflow(
                    obj=claim,
                    code="claim_review",
                    actor=request.user,
                    assignee=assignee,
                    delegation=delegation,
                    note="خسارت دستی ثبت و برای ارزیابی تخصصی ارجاع شد.",
                )
                record_event(
                    actor=request.user,
                    action="claim_manual_created",
                    obj=claim,
                    summary="خسارت دستی ثبت و برای ارزیابی ارجاع شد.",
                    after_data={
                        "claim_number": claim.claim_number,
                        "person_id": claim.person_id,
                        "company_id": company.pk,
                        "insurer_id": contract.insurer_id,
                        "contract_id": contract.pk,
                        "workflow_case_id": case.pk,
                    },
                    request=request,
                )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "خسارت ثبت و برای ارزیابی تخصصی ارجاع شد.")
            return redirect("claim_detail", pk=claim.pk)
    return render(request, "claims/claim_form.html", {"form": form})


@login_required
@require_POST
def claim_assess(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    case = _claim_workflow_case(claim)
    if (
        not case
        or not case.current_step
        or case.current_step.code not in {"under_review", "needs_info"}
        or not (case.current_assignee_id == request.user.pk or has_global_access(request.user))
        or not can_decide_claim(request.user, claim)
    ):
        raise PermissionDenied

    form = ClaimAssessmentForm(request.POST, claim=claim)
    if not form.is_valid():
        messages.error(request, "اطلاعات ارزیابی معتبر نیست: " + " ".join(
            str(error) for error in form.errors.values()
        ))
        return redirect("claim_detail", pk=claim.pk)

    with transaction.atomic():
        claim = Claim.objects.select_for_update().get(pk=claim.pk)
        previous = {
            "assessed_amount": str(claim.assessed_amount),
            "payable_amount": str(claim.payable_amount),
            "assessment_note": claim.assessment_note,
        }
        claim.assessed_amount = form.cleaned_data["assessed_amount"]
        claim.payable_amount = form.cleaned_data["payable_amount"]
        claim.assessment_note = form.cleaned_data["assessment_note"].strip()
        claim.assessed_by = request.user
        claim.assessed_at = timezone.now()
        claim.save(update_fields=[
            "assessed_amount", "payable_amount", "assessment_note",
            "assessed_by", "assessed_at", "updated_at",
        ])
        record_event(
            actor=request.user,
            action="claim_assessed",
            obj=claim,
            summary="ارزیابی غیرپزشکی خسارت ثبت شد.",
            before_data=previous,
            after_data={
                "assessed_amount": str(claim.assessed_amount),
                "payable_amount": str(claim.payable_amount),
                "assessment_note": claim.assessment_note,
            },
            request=request,
        )
    messages.success(request, "ارزیابی ثبت شد؛ برای تصمیم نهایی، گردش کار را به مرجع مجاز ارجاع دهید.")
    return redirect("claim_detail", pk=claim.pk)


@login_required
@require_POST
def claim_result_send(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    case = _claim_workflow_case(claim)
    if (
        claim.status not in {Claim.Status.APPROVED, Claim.Status.REJECTED}
        or claim.result_sent_at
        or not case
        or case.status != WorkflowCase.Status.CLOSED
        or not can_decide_claim(request.user, claim)
    ):
        raise PermissionDenied("ارسال نتیجه فقط پس از تصمیم و بستن گردش ارزیابی مجاز است.")
    claim.result_sent_at = timezone.now()
    claim.result_sent_by = request.user
    claim.save(update_fields=["result_sent_at", "result_sent_by", "updated_at"])
    record_event(
        actor=request.user,
        action="claim_result_sent",
        obj=claim,
        summary="نتیجه رسیدگی به بیمه‌شده اعلام شد؛ مهلت ۶۰ روزه اعتراض آغاز شد.",
        after_data={
            "result_sent_at": claim.result_sent_at.isoformat(),
            "result_sent_by": request.user.pk,
            "objection_deadline": claim.objection_deadline.isoformat(),
        },
        request=request,
    )
    messages.success(request, "زمان اعلام نتیجه ثبت شد و مهلت ۶۰ روزه اعتراض آغاز گردید.")
    return redirect("claim_detail", pk=claim.pk)



@login_required
@require_POST
def claim_duplicate_declare(request, pk):
    claim = get_object_or_404(scoped_claims_for(request.user), pk=pk)
    if not (
        claim.insurer_id
        and claim.contract_id
        and has_role(
            request.user,
            RoleAssignment.Role.INSURER_REP,
            insurer_id=claim.insurer_id,
            line_code=claim.contract.line,
        )
    ):
        raise PermissionDenied
    if claim.source_duplicate_status == Claim.DuplicateStatus.DECLARED_DUPLICATE:
        raise PermissionDenied("تکراری بودن این پرونده قبلاً توسط بیمه‌گر اعلام شده است.")

    form = ClaimDuplicateDeclarationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "شماره پرونده اصلی و توضیح رسمی بیمه‌گر الزامی است.")
        return redirect("claim_detail", pk=claim.pk)

    with transaction.atomic():
        claim = Claim.objects.select_for_update().get(pk=claim.pk)
        if claim.source_duplicate_status == Claim.DuplicateStatus.DECLARED_DUPLICATE:
            raise PermissionDenied("تکراری بودن این پرونده قبلاً اعلام شده است.")
        claim.source_duplicate_status = Claim.DuplicateStatus.DECLARED_DUPLICATE
        claim.source_duplicate_reference = form.cleaned_data["source_duplicate_reference"].strip()
        claim.source_duplicate_note = form.cleaned_data["source_duplicate_note"].strip()
        claim.source_duplicate_reported_at = timezone.now()
        claim.source_duplicate_reported_by = request.user
        claim.save(update_fields=[
            "source_duplicate_status", "source_duplicate_reference",
            "source_duplicate_note", "source_duplicate_reported_at",
            "source_duplicate_reported_by", "updated_at",
        ])
        recipient_person = claim.primary_insured or claim.person
        if recipient_person.user_id:
            UserNotification.objects.create(
                recipient=recipient_person.user,
                actor=request.user,
                title="اعلام تکراری بودن پرونده خسارت",
                body="بیمه‌گر این پرونده را تکراری اعلام کرده است. برای مشاهده جزئیات و مرجع اعلام، پرونده خسارت را باز کنید.",
                target_url=reverse("claim_detail", args=[claim.pk]),
            )
        record_event(
            actor=request.user,
            action="claim_duplicate_declared_by_insurer",
            obj=claim,
            summary="بیمه‌گر این پرونده را به‌صورت رسمی تکراری اعلام کرد.",
            after_data={
                "source_duplicate_reference": claim.source_duplicate_reference,
                "source_duplicate_note": claim.source_duplicate_note,
                "reported_at": claim.source_duplicate_reported_at.isoformat(),
                "reported_by": request.user.pk,
            },
            request=request,
        )
    messages.success(request, "اعلام تکراری بودن توسط بیمه‌گر ثبت شد.")
    return redirect("claim_detail", pk=claim.pk)
