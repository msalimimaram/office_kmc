from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access
from workflow.models import WorkflowCase

from .forms import WorkDelegationForm
from .models import WorkDelegation
from .services import create_work_delegation, synchronize_delegations, update_delegation_status


@login_required
def delegation_inbox(request):
    # The inbox is private to the delegator, the recipient, and global managers.
    if (
        not has_global_access(request.user)
        and not WorkDelegation.objects.filter(delegate_to=request.user).exists()
    ):
        raise PermissionDenied("صندوق تفویض فقط برای گیرنده تفویض یا مدیران مجاز است.")
    synchronize_delegations()
    cases = WorkflowCase.objects.filter(
        current_assignee=request.user,
        delegation__isnull=False,
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
    ).select_related(
        "definition", "current_step", "delegation", "delegation__granted_by",
    ).order_by("sla_due_at", "opened_at")
    today = timezone.localdate()
    active_rules = WorkDelegation.objects.filter(
        delegate_to=request.user,
        status=WorkDelegation.Status.ACTIVE,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    case_count = cases.count()
    overdue_count = cases.filter(sla_due_at__lt=timezone.now()).count()
    page_obj = Paginator(cases, 25).get_page(request.GET.get("page"))
    return render(request, "delegations/delegation_inbox.html", {
        "cases": page_obj.object_list,
        "page_obj": page_obj,
        "case_count": case_count,
        "overdue_count": overdue_count,
        "active_rule_count": active_rules.count(),
    })


@login_required
def delegation_management(request):
    if not has_global_access(request.user):
        raise PermissionDenied
    # Also reconcile expired rules and receiver assignments before rendering
    # the management screen; this is the same operation used by the inbox.
    synchronize_delegations()
    form = WorkDelegationForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action", "create")
        try:
            if action == "create":
                if form.is_valid():
                    delegation, routed = create_work_delegation(
                        cleaned_data=form.cleaned_data, actor=request.user,
                    )
                    messages.success(
                        request,
                        f"تفویض ثبت شد؛ {routed} پرونده باز واجد شرایط نیز به گیرنده منتقل شد.",
                    )
                    return redirect("delegation_management")
            else:
                update_delegation_status(
                    delegation_id=request.POST.get("delegation_id"),
                    actor=request.user,
                    action=action,
                    reason=request.POST.get("reason", "").strip(),
                )
                messages.success(request, "وضعیت تفویض اختیار به‌روزرسانی شد.")
                return redirect("delegation_management")
        except (ValidationError, PermissionDenied, ValueError, WorkDelegation.DoesNotExist) as exc:
            messages.error(request, str(exc))
    rules = WorkDelegation.objects.select_related(
        "delegate_to", "granted_by", "company", "insurer",
    ).prefetch_related("events").order_by("-created_at")
    return render(request, "delegations/delegation_list.html", {
        "form": form,
        "delegations": rules,
    })
