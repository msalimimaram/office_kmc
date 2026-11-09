from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Max
from django.shortcuts import get_object_or_404, redirect, render

from accounts.access import company_ids_for, has_global_access, has_role, insurer_ids_for, line_codes_for
from accounts.models import RoleAssignment
from auditlog.services import record_event
from workflow.models import WorkflowCase, WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow

from .forms import ContractForm
from .models import Contract, ContractRevision, InsuranceLine


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


def _can_submit_contract(user, line=None):
    if has_global_access(user):
        return True
    if line:
        return has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line)
    return has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)


def _snapshot_from_form(form):
    cleaned = form.cleaned_data
    return {
        "code": cleaned["code"],
        "title": cleaned["title"],
        "insurer_id": cleaned["insurer"].pk,
        "line": cleaned["line"],
        "start_date": cleaned["start_date"].isoformat(),
        "end_date": cleaned["end_date"].isoformat(),
        "coverage_summary": cleaned.get("coverage_summary", ""),
        "terms": cleaned.get("terms", ""),
        "company_ids": sorted(company.pk for company in cleaned["companies"]),
    }


def _start_contract_revision(*, contract, form, actor, revision_number, code):
    definition = WorkflowDefinition.objects.filter(
        code=code, is_active=True
    ).order_by("-version").first()
    if not definition:
        raise ValidationError(f"گردش‌کار فعال {code} برای تأیید قرارداد پیکربندی نشده است.")

    revision = ContractRevision.objects.create(
        contract=contract,
        revision_number=revision_number,
        description=form.cleaned_data["revision_description"],
        document=form.cleaned_data.get("revision_document"),
        created_by=actor,
        status=ContractRevision.Status.PENDING_APPROVAL,
        snapshot=_snapshot_from_form(form),
        effective_date=form.cleaned_data["effective_date"],
    )
    assignee = resolve_initial_assignee(
        definition=definition,
        insurer_id=contract.insurer_id,
        line_code=contract.line,
    )
    case = start_workflow(
        obj=revision,
        code=code,
        actor=actor,
        assignee=assignee,
        note=form.cleaned_data["revision_description"],
    )
    return revision, case


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
    page_obj = Paginator(
        contracts.distinct().order_by("-start_date", "code", "pk"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "insurance/contract_list.html", {
        "contracts": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
        "selected_line": line,
        "lines": InsuranceLine.choices,
        "selected_state": state,
        "can_create_contract": _can_submit_contract(request.user),
    })


@login_required
def contract_create(request):
    if not _can_submit_contract(request.user):
        raise PermissionDenied
    form = ContractForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                contract = form.save(commit=False)
                contract.status = Contract.Status.DRAFT
                contract.is_active = False
                contract.save()
                form.save_m2m()
                revision, case = _start_contract_revision(
                    contract=contract,
                    form=form,
                    actor=request.user,
                    revision_number=1,
                    code="contract_approval",
                )
                record_event(
                    actor=request.user,
                    action="contract_submitted_for_approval",
                    obj=contract,
                    summary="قرارداد جدید برای تأیید رئیس اداره/مدیر سامانه ارسال شد.",
                    after_data={
                        "revision_id": revision.pk,
                        "workflow_case_id": case.pk,
                        "revision_number": revision.revision_number,
                        "effective_date": revision.effective_date.isoformat(),
                    },
                    request=request,
                )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "پیش‌نویس قرارداد ثبت و برای تأیید ارجاع شد.")
            return redirect("contract_detail", pk=contract.pk)
    return render(request, "insurance/contract_form.html", {
        "form": form,
        "page_title": "ثبت قرارداد جدید",
        "submit_label": "ثبت و ارسال برای تأیید",
    })


@login_required
def contract_detail(request, pk):
    contract = get_object_or_404(_contract_scope(request.user), pk=pk)
    revisions = list(contract.revisions.select_related("created_by", "approved_by").all())
    if revisions:
        content_type = ContentType.objects.get_for_model(
            ContractRevision, for_concrete_model=False
        )
        cases = WorkflowCase.objects.filter(
            content_type=content_type,
            object_id__in=[str(revision.pk) for revision in revisions],
        ).select_related("current_step", "current_assignee")
        cases_by_object = {case.object_id: case for case in cases}
        for revision in revisions:
            revision.workflow_case = cases_by_object.get(str(revision.pk))
    can_submit_revision = _can_submit_contract(request.user, contract.line)
    return render(request, "insurance/contract_detail.html", {
        "contract": contract,
        "revisions": revisions,
        "can_submit_revision": can_submit_revision,
    })


@login_required
def contract_revision_create(request, pk):
    contract = get_object_or_404(_contract_scope(request.user), pk=pk)
    if not _can_submit_contract(request.user, contract.line):
        raise PermissionDenied
    form = ContractForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        instance=contract,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                revision_number = (
                    contract.revisions.aggregate(value=Max("revision_number"))["value"] or 0
                ) + 1
                revision, case = _start_contract_revision(
                    contract=contract,
                    form=form,
                    actor=request.user,
                    revision_number=revision_number,
                    code="contract_approval",
                )
                record_event(
                    actor=request.user,
                    action="contract_revision_submitted",
                    obj=contract,
                    summary="نسخه جدید قرارداد برای تأیید ارسال شد؛ نسخه جاری تا تأیید تغییر نمی‌کند.",
                    after_data={
                        "revision_id": revision.pk,
                        "revision_number": revision.revision_number,
                        "workflow_case_id": case.pk,
                        "effective_date": revision.effective_date.isoformat(),
                    },
                    request=request,
                )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "نسخه جدید برای تأیید ارسال شد؛ نسخه جاری بدون تغییر باقی ماند.")
            return redirect("contract_detail", pk=contract.pk)
    return render(request, "insurance/contract_form.html", {
        "form": form,
        "page_title": f"ثبت نسخه جدید قرارداد {contract.code}",
        "submit_label": "ارسال نسخه برای تأیید",
        "contract": contract,
    })
