from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.access import active_internal_position_assignments, has_global_access, has_role, is_unit_manager, line_codes_for
from accounts.models import OrganizationalPosition, RoleAssignment, User
from auditlog.services import record_event
from tasks.forms import _manager_scope
from workflow.models import WorkflowCase, WorkflowDefinition
from workflow.services import (
    resolve_initial_assignee, start_workflow, transition_case,
)
from .forms import ReportRevisionForm, ReportSubmissionForm
from .models import Report, ReportVersion


def _report_content_type():
    return ContentType.objects.get_for_model(Report, for_concrete_model=False)


def _visible_reports(user):
    qs = Report.objects.select_related("created_by", "assigned_to", "company").prefetch_related("versions")
    if has_global_access(user):
        return qs
    if not (
        has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)
        or is_unit_manager(user)
    ):
        return Report.objects.none()

    case_scope = WorkflowCase.objects.filter(content_type=_report_content_type())
    allowed_ids = case_scope.filter(
        Q(current_assignee=user) | Q(events__from_assignee=user)
    ).values("object_id")
    allowed = Q(created_by=user) | Q(pk__in=allowed_ids)

    if is_unit_manager(user):
        subordinate_ids = User.objects.filter(_manager_scope(user)).values("pk")
        allowed |= Q(created_by_id__in=subordinate_ids)
        allowed |= Q(pk__in=case_scope.filter(
            current_assignee_id__in=subordinate_ids
        ).values("object_id"))

    lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
    if lines and "*" not in lines:
        allowed &= Q(line_code__in=lines) | Q(created_by=user)
    return qs.filter(allowed).distinct()


def _case_for_report(report):
    return WorkflowCase.objects.filter(
        content_type=_report_content_type(), object_id=str(report.pk)
    ).select_related(
        "definition", "current_step", "current_assignee", "current_position_assignment",
        "delegation",
    ).order_by("-definition__is_active", "-definition__version", "-pk").first()


@login_required
def report_list(request):
    if not (
        has_global_access(request.user)
        or has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST)
        or is_unit_manager(request.user)
    ):
        raise PermissionDenied
    page_obj = Paginator(
        _visible_reports(request.user).order_by("-updated_at", "-pk"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "reports/report_list.html", {
        "reports": page_obj.object_list,
        "page_obj": page_obj,
        "can_create": has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST),
    })


@login_required
def report_create(request):
    if not has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        raise PermissionDenied("تهیه و ثبت گزارش برای کارشناس اداره بیمه مجاز است.")
    if not active_internal_position_assignments(request.user).filter(
        position__level=OrganizationalPosition.Level.SPECIALIST
    ).exists():
        raise PermissionDenied("برای ارسال گزارش در سلسله‌مراتب، انتصاب معتبر کارشناس الزامی است.")

    form = ReportSubmissionForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        definition = WorkflowDefinition.objects.filter(
            code="management_report_approval", is_active=True
        ).order_by("-version").first()
        if not definition:
            form.add_error(None, "گردش‌کار فعال گزارش مدیریتی منتشر نشده است.")
        else:
            try:
                with transaction.atomic():
                    report = form.save(commit=False)
                    report.created_by = request.user
                    report.status = Report.Status.DRAFT
                    report.save()
                    version = ReportVersion.objects.create(
                        report=report,
                        version_number=1,
                        summary=form.cleaned_data["summary"].strip(),
                        body=form.cleaned_data["body"].strip(),
                        created_by=request.user,
                    )
                    assignee, delegation = resolve_initial_assignee(
                        definition=definition,
                        obj=report,
                        line_code=report.line_code,
                        owner_user_id=request.user.pk,
                        return_delegation=True,
                    )
                    case = start_workflow(
                        obj=report,
                        code="management_report_approval",
                        actor=request.user,
                        assignee=assignee,
                        delegation=delegation,
                        note=version.summary,
                    )
                    record_event(
                        actor=request.user,
                        action="management_report_submitted",
                        obj=report,
                        summary="نسخه اول گزارش برای بررسی سلسله‌مراتبی ارسال شد.",
                        after_data={
                            "version_id": version.pk,
                            "workflow_case_id": case.pk,
                            "line_code": report.line_code,
                            "company_id": report.company_id,
                        },
                        request=request,
                    )
            except (ValidationError, PermissionDenied) as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "گزارش ثبت و برای بررسی سرپرست ارجاع شد.")
                return redirect("report_detail", pk=report.pk)

    return render(request, "reports/report_form.html", {
        "form": form,
        "page_title": "تهیه گزارش مدیریتی",
    })


@login_required
def report_detail(request, pk):
    report = get_object_or_404(_visible_reports(request.user), pk=pk)
    case = _case_for_report(report)
    if case and (
        has_global_access(request.user)
        or (
            case.current_assignee_id == request.user.pk
            and not (
                report.created_by_id == request.user.pk
                and case.current_step
                and case.current_step.code == Report.Status.RETURNED
            )
        )
    ):
        return redirect("workflow_case_detail", pk=case.pk)

    can_resubmit = bool(
        case
        and report.created_by_id == request.user.pk
        and case.current_assignee_id == request.user.pk
        and case.current_step
        and case.current_step.code == Report.Status.RETURNED
    )
    form = ReportRevisionForm(request.POST or None) if can_resubmit else None
    if request.method == "POST":
        if not can_resubmit or form is None or not form.is_valid():
            raise PermissionDenied("ثبت نسخه جدید فقط برای تهیه‌کننده گزارش بازگشتی مجاز است.")
        try:
            with transaction.atomic():
                locked_report = Report.objects.select_for_update().get(pk=report.pk)
                locked_case = WorkflowCase.objects.select_for_update().get(pk=case.pk)
                next_number = (locked_report.versions.aggregate(value=models.Max("version_number"))["value"] or 0) + 1
                version = ReportVersion.objects.create(
                    report=locked_report,
                    version_number=next_number,
                    summary=form.cleaned_data["summary"].strip(),
                    body=form.cleaned_data["body"].strip(),
                    created_by=request.user,
                )
                definition = WorkflowDefinition.objects.filter(
                    code="management_report_approval", is_active=True
                ).order_by("-version").first()
                if not definition:
                    raise ValidationError("گردش‌کار گزارش مدیریتی فعال نیست.")
                assignee, delegation = resolve_initial_assignee(
                    definition=definition,
                    obj=locked_report,
                    line_code=locked_report.line_code,
                    owner_user_id=request.user.pk,
                    return_delegation=True,
                )
                transition_case(
                    case_id=locked_case.pk,
                    actor=request.user,
                    action_code="resubmit",
                    recipient=assignee,
                    note=version.summary,
                )
                record_event(
                    actor=request.user,
                    action="management_report_revision_submitted",
                    obj=locked_report,
                    summary=f"نسخه {version.version_number} گزارش برای بررسی مجدد ارسال شد.",
                    after_data={"version_id": version.pk, "workflow_case_id": locked_case.pk},
                    request=request,
                )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "نسخه جدید ثبت و دوباره به مسیر بررسی ارسال شد.")
            return redirect("report_detail", pk=report.pk)

    return render(request, "reports/report_detail.html", {
        "report": report,
        "case": case,
        "versions": report.versions.select_related("created_by").all(),
        "form": form,
        "can_resubmit": can_resubmit,
    })
