from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from accounts.access import active_assignments, has_global_access
from accounts.models import UserNotification, RoleAssignment
from workflow.models import WorkflowCase, WorkflowEvent

from .models import WorkDelegation, DelegationEvent


User = get_user_model()


def _role_assignment_is_active(delegation):
    assignments = active_assignments(delegation.delegate_to).filter(role=delegation.delegate_role)
    if delegation.delegate_role == RoleAssignment.Role.INSURANCE_SPECIALIST:
        return bool(
            delegation.line_code
            and assignments.filter(line_code__in=[delegation.line_code, "*"]).exists()
        )
    if delegation.delegate_role == RoleAssignment.Role.SUBSIDIARY_REP:
        return bool(
            delegation.company_id
            and assignments.filter(company_id=delegation.company_id).exists()
        )
    if delegation.delegate_role == RoleAssignment.Role.INSURER_REP:
        return bool(
            delegation.insurer_id and assignments.filter(insurer_id=delegation.insurer_id).exists()
        )
    return False


def delegation_matches(delegation, *, workflow_code, item_type="", scope=None):
    scope = scope or {}
    today = timezone.localdate()
    if (
        delegation.status != WorkDelegation.Status.ACTIVE
        or delegation.valid_from > today
        or (delegation.valid_until and delegation.valid_until < today)
        or delegation.workflow_code != workflow_code
    ):
        return False
    if delegation.item_type and delegation.item_type != (item_type or ""):
        return False
    for field in ("company_id", "insurer_id", "line_code"):
        required = getattr(delegation, field)
        if required and required != scope.get(field):
            return False
    return _role_assignment_is_active(delegation)


def find_matching_delegation(*, workflow_code, item_type="", company_id=None, insurer_id=None, line_code=None):
    today = timezone.localdate()
    rules = WorkDelegation.objects.select_related("delegate_to").filter(
        workflow_code=workflow_code,
        status=WorkDelegation.Status.ACTIVE,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    matches = []
    scope = {"company_id": company_id, "insurer_id": insurer_id, "line_code": line_code}
    for rule in rules:
        if rule.item_type and rule.item_type != (item_type or ""):
            continue
        if rule.company_id and rule.company_id != company_id:
            continue
        if rule.insurer_id and rule.insurer_id != insurer_id:
            continue
        if rule.line_code and rule.line_code != line_code:
            continue
        score = (bool(rule.item_type), bool(rule.company_id), bool(rule.insurer_id), bool(rule.line_code))
        matches.append((score, rule))
    if not matches:
        return None
    best_score = max(score for score, _rule in matches)
    best = [rule for score, rule in matches if score == best_score]
    if len(best) > 1:
        raise ValidationError("چند تفویض اختیار هم‌سطح برای این نوع کار و محدوده فعال است؛ ابتدا تعارض را رفع کنید.")
    selected = best[0]
    if not delegation_matches(selected, workflow_code=workflow_code, item_type=item_type, scope=scope):
        raise ValidationError("گیرنده تفویض دیگر انتصاب معتبر ندارد؛ تفویض را اصلاح یا لغو کنید.")
    return selected


def _notify(recipient, actor, title, body, target_url):
    if not recipient or not recipient.is_active:
        return
    UserNotification.objects.create(
        recipient=recipient, actor=actor, title=title, body=body,
        target_url=target_url,
    )


def _route_case(case, delegation, actor, *, event_type, note):
    previous = case.current_assignee
    case.current_assignee = delegation.delegate_to
    case.delegation = delegation
    case.save(update_fields=["current_assignee", "delegation"])
    WorkflowEvent.objects.create(
        workflow_case=case, actor=actor,
        event_type=WorkflowEvent.EventType.REFERRED,
        action_code="delegation_route",
        from_step=case.current_step, to_step=case.current_step,
        from_assignee=previous, to_assignee=delegation.delegate_to,
        note=note, sent_at=timezone.now(),
        metadata={"delegation_id": delegation.pk, "event": event_type},
    )
    DelegationEvent.objects.create(
        delegation=delegation, actor=actor, event_type=event_type,
        summary=note[:1000],
        metadata={"workflow_case_id": case.pk, "from_assignee_id": getattr(previous, "pk", None)},
    )
    _notify(
        delegation.delegate_to, actor, "پرونده به‌صورت گروهی به شما واگذار شد",
        f"پرونده {case.definition.title} طبق تفویض معتبر به صندوق کارهای شما منتقل شد.",
        reverse("workflow_case_detail", args=[case.pk]),
    )


def apply_delegation_to_open_cases(delegation, *, actor=None):
    from workflow.services import _scope_for_object

    actor = actor or delegation.granted_by
    cases = WorkflowCase.objects.select_related(
        "definition", "current_step", "current_assignee", "delegation", "content_type"
    ).filter(
        definition__code=delegation.workflow_code,
        current_step__is_initial=True,
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
    )
    routed = 0
    for case in cases:
        obj = case.content_object
        if obj is None:
            continue
        scope = _scope_for_object(obj)
        item_type = str(
            getattr(obj, "change_type", None)
            or getattr(obj, "kind", None)
            or ""
        )
        if not delegation_matches(
            delegation, workflow_code=case.definition.code,
            item_type=item_type, scope=scope,
        ):
            continue
        if case.current_assignee_id == delegation.delegate_to_id and case.delegation_id == delegation.pk:
            continue
        _route_case(
            case, delegation, actor,
            event_type=DelegationEvent.EventType.CASE_ROUTED,
            note=f"ارجاع خودکار پرونده به دلیل تفویض دسته‌ای: {delegation.reason}",
        )
        routed += 1
    return routed


@transaction.atomic
def create_work_delegation(*, cleaned_data, actor):
    if not has_global_access(actor):
        raise PermissionDenied("ایجاد تفویض اختیار فقط برای رئیس اداره یا مدیر سامانه مجاز است.")
    delegate = cleaned_data["delegate_to"]
    if delegate.pk == actor.pk or not delegate.is_active:
        raise ValidationError("گیرنده تفویض باید کاربر فعال دیگری باشد.")
    delegation = WorkDelegation(
        workflow_code=cleaned_data["workflow_code"],
        item_type=cleaned_data.get("item_type") or "",
        delegate_role=cleaned_data["delegate_role"],
        delegate_to=delegate,
        granted_by=actor,
        company=cleaned_data.get("company"),
        insurer=cleaned_data.get("insurer"),
        line_code=cleaned_data.get("line_code") or "",
        valid_from=cleaned_data["valid_from"],
        valid_until=cleaned_data.get("valid_until"),
        reason=cleaned_data["reason"].strip(),
    )
    if not _role_assignment_is_active(delegation):
        raise ValidationError("گیرنده در محدوده انتخاب‌شده انتصاب فعال ندارد.")
    delegation.save()
    DelegationEvent.objects.create(
        delegation=delegation, actor=actor,
        event_type=DelegationEvent.EventType.CREATED,
        summary="تفویض اختیار گروهی ثبت شد.",
        metadata={
            "workflow_code": delegation.workflow_code,
            "item_type": delegation.item_type,
            "delegate_role": delegation.delegate_role,
            "delegate_to_id": delegate.pk,
            "company_id": delegation.company_id,
            "insurer_id": delegation.insurer_id,
            "line_code": delegation.line_code,
            "valid_from": delegation.valid_from.isoformat(),
            "valid_until": delegation.valid_until.isoformat() if delegation.valid_until else None,
        },
    )
    routed = apply_delegation_to_open_cases(delegation, actor=actor)
    _notify(
        delegate, actor, "تفویض اختیار جدید برای شما ثبت شد",
        f"مسئولیت گردش‌کار {delegation.workflow_code} به محدوده شما واگذار شد. پرونده‌های جاری واجد شرایط: {routed} مورد.",
        reverse("delegation_inbox"),
    )
    return delegation, routed


def _release_cases(delegation, *, actor, event_type, note):
    cases = WorkflowCase.objects.select_related(
        "definition", "current_step", "current_assignee", "content_type"
    ).filter(
        delegation=delegation,
        current_assignee=delegation.delegate_to,
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
    )
    released = 0
    for case in cases:
        previous = case.current_assignee
        replacement = delegation.granted_by if delegation.granted_by.is_active else None
        case.current_assignee = replacement
        case.save(update_fields=["current_assignee"])
        WorkflowEvent.objects.create(
            workflow_case=case, actor=actor,
            event_type=WorkflowEvent.EventType.RETURNED,
            action_code="delegation_release",
            from_step=case.current_step, to_step=case.current_step,
            from_assignee=previous, to_assignee=replacement,
            note=note[:4000], sent_at=timezone.now(),
            metadata={"delegation_id": delegation.pk, "event": event_type},
        )
        DelegationEvent.objects.create(
            delegation=delegation, actor=actor,
            event_type=DelegationEvent.EventType.CASE_RETURNED,
            summary=note[:1000],
            metadata={"workflow_case_id": case.pk, "to_assignee_id": getattr(replacement, "pk", None)},
        )
        if replacement:
            _notify(
                replacement, actor, "پرونده از تفویض خارج شد",
                f"پرونده {case.definition.title} پس از تغییر وضعیت تفویض به شما بازگشت.",
                reverse("workflow_case_detail", args=[case.pk]),
            )
        released += 1
    return released


@transaction.atomic
def update_delegation_status(*, delegation_id, actor, action, reason=""):
    if not has_global_access(actor):
        raise PermissionDenied("مدیریت تفویض اختیار فقط برای رئیس اداره یا مدیر سامانه مجاز است.")
    delegation = WorkDelegation.objects.select_for_update().get(pk=delegation_id)
    if action == "suspend":
        if delegation.status != WorkDelegation.Status.ACTIVE:
            raise ValidationError("فقط تفویض فعال قابل تعلیق است.")
        delegation.status = WorkDelegation.Status.SUSPENDED
        event_type = DelegationEvent.EventType.SUSPENDED
    elif action == "resume":
        if delegation.status != WorkDelegation.Status.SUSPENDED or (
            delegation.valid_until and delegation.valid_until < timezone.localdate()
        ):
            raise ValidationError("این تفویض قابل فعال‌سازی مجدد نیست؛ تاریخ اعتبار را بررسی کنید.")
        delegation.status = WorkDelegation.Status.ACTIVE
        event_type = DelegationEvent.EventType.RESUMED
    elif action == "revoke":
        if delegation.status in {WorkDelegation.Status.REVOKED, WorkDelegation.Status.EXPIRED}:
            raise ValidationError("تفویض قبلاً خاتمه یافته است.")
        delegation.status = WorkDelegation.Status.REVOKED
        delegation.revoked_at = timezone.now()
        delegation.revoked_by = actor
        event_type = DelegationEvent.EventType.REVOKED
    else:
        raise ValidationError("عملیات وضعیت تفویض معتبر نیست.")
    delegation.revocation_reason = (reason or "").strip()
    delegation.save(update_fields=["status", "revoked_at", "revoked_by", "revocation_reason", "updated_at"])
    DelegationEvent.objects.create(
        delegation=delegation, actor=actor, event_type=event_type,
        summary=(reason or event_type.label).strip()[:1000],
        metadata={"status": delegation.status},
    )
    if action in {"suspend", "revoke"}:
        _release_cases(
            delegation, actor=actor, event_type=event_type,
            note=f"پرونده به علت {event_type.label} تفویض به تفویض‌کننده بازگردانده شد. {reason}".strip(),
        )
    else:
        apply_delegation_to_open_cases(delegation, actor=actor)
    return delegation


@transaction.atomic
def expire_due_delegations():
    today = timezone.localdate()
    due = WorkDelegation.objects.select_for_update().filter(
        status=WorkDelegation.Status.ACTIVE, valid_until__lt=today,
    )
    count = 0
    for delegation in due:
        delegation.status = WorkDelegation.Status.EXPIRED
        delegation.save(update_fields=["status", "updated_at"])
        actor = delegation.granted_by
        DelegationEvent.objects.create(
            delegation=delegation, actor=actor,
            event_type=DelegationEvent.EventType.EXPIRED,
            summary="تفویض اختیار به پایان تاریخ اعتبار منقضی شد.",
            metadata={"expired_on": today.isoformat()},
        )
        _release_cases(
            delegation, actor=actor,
            event_type=DelegationEvent.EventType.EXPIRED,
            note="پایان اعتبار تفویض؛ پرونده به تفویض‌کننده بازگشت.",
        )
        count += 1
    return count
