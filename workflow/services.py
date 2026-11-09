from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from .models import (
    BusinessCalendar, WorkflowCase, WorkflowDefinition, WorkflowEvent,
    WorkflowStep, WorkflowTransition,
)


User = get_user_model()


HEALTH_REQUEST_KINDS = {
    "medical_assistance", "anonymous_plan", "excess_coverage",
    "add_coverage", "remove_coverage", "base_insurance_waiver",
}


def _infer_insurer_id(company_id, line_code):
    if not company_id or not line_code:
        return None
    from insurance.models import Contract
    today = timezone.localdate()
    insurer_ids = list(
        Contract.objects.filter(
            companies__id=company_id,
            line=line_code,
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        ).values_list("insurer_id", flat=True).distinct()[:2]
    )
    return insurer_ids[0] if len(insurer_ids) == 1 else None


def _scope_for_object(obj, _seen=None):
    """Resolve authorization scope from a domain object or its parent record.

    Nested workflow records (for example a claim objection or an asset
    endorsement) inherit company/insurer/line scope from their owning record.
    Explicit scope on the child always takes precedence.
    """
    if obj is None:
        return {"company_id": None, "insurer_id": None, "line_code": None, "owner_user_id": None}
    seen = _seen if _seen is not None else set()
    marker = (obj.__class__, getattr(obj, "pk", None) or id(obj))
    if marker in seen:
        return {"company_id": None, "insurer_id": None, "line_code": None, "owner_user_id": None}
    seen.add(marker)

    company_id = getattr(obj, "company_id", None) or getattr(obj, "company_snapshot_id", None)
    insurer_id = getattr(obj, "insurer_id", None)
    line_code = getattr(obj, "line_code", None)
    if not line_code and getattr(obj, "kind", None) in HEALTH_REQUEST_KINDS:
        line_code = "health"
    owner_user_id = getattr(obj, "submitted_by_id", None) or getattr(obj, "user_id", None)
    person = getattr(obj, "person", None)
    if person is not None:
        company_id = company_id or getattr(person, "company_id", None)
        if owner_user_id is None:
            owner = getattr(person, "user", None) or getattr(getattr(person, "employee", None), "user", None)
            owner_user_id = getattr(owner, "pk", None)
    contract = getattr(obj, "contract", None)
    if contract:
        insurer_id = insurer_id or getattr(contract, "insurer_id", None)
        line_code = line_code or getattr(contract, "line", None)

    # Follow only known ownership relations; do not walk arbitrary model
    # relations or infer scope from a user-supplied content-type target.
    for relation_name in ("claim", "policy_period", "asset", "correspondence", "service_request"):
        parent = getattr(obj, relation_name, None)
        if parent is None or parent is obj:
            continue
        parent_scope = _scope_for_object(parent, seen)
        company_id = company_id or parent_scope["company_id"]
        insurer_id = insurer_id or parent_scope["insurer_id"]
        line_code = line_code or parent_scope["line_code"]
        owner_user_id = owner_user_id or parent_scope["owner_user_id"]

    insurer_id = insurer_id or _infer_insurer_id(company_id, line_code)
    return {
        "company_id": company_id,
        "insurer_id": insurer_id,
        "line_code": line_code,
        "owner_user_id": owner_user_id,
    }


def _has_any_role(
    user, roles, *, company_id=None, insurer_id=None, line_code=None, owner_user_id=None
):
    if not user or not user.is_authenticated or not user.is_active or not roles:
        return False
    for role in roles:
        # A scoped role must never become an unscoped role because an object
        # lacks the corresponding scope field.
        if role == RoleAssignment.Role.SUBSIDIARY_REP and company_id is None:
            continue
        if role == RoleAssignment.Role.INSURER_REP and insurer_id is None:
            continue
        if role == RoleAssignment.Role.INSURANCE_SPECIALIST and not line_code:
            continue
        if role == RoleAssignment.Role.INSURED_PERSON and owner_user_id != user.pk:
            continue
        if has_role(
            user,
            role,
            company_id=company_id if role == RoleAssignment.Role.SUBSIDIARY_REP else None,
            insurer_id=insurer_id if role == RoleAssignment.Role.INSURER_REP else None,
            line_code=line_code if role in {
                RoleAssignment.Role.INSURANCE_SPECIALIST,
                RoleAssignment.Role.SUBSIDIARY_REP,
            } else None,
        ):
            return True
    return False


def _sync_domain_status(obj, *, step_code=None, closed=False):
    """Synchronize an opted-in domain status when a workflow step uses its choice key."""
    if obj is None or not hasattr(obj, "status"):
        return
    status_model = getattr(obj, "Status", None)
    choices = getattr(status_model, "choices", ())
    allowed = dict(choices)
    target = "closed" if closed and "closed" in allowed else step_code
    if not target or target not in allowed or getattr(obj, "status", None) == target:
        return
    obj.status = target
    update_fields = ["status"]
    if any(field.name == "updated_at" for field in obj._meta.fields):
        update_fields.append("updated_at")
    obj.save(update_fields=update_fields)


def _calendar_is_working_day(calendar, day):
    holiday = calendar.holidays.filter(date=day).first()
    if holiday:
        return holiday.is_working_override
    return day.weekday() in (calendar.working_weekdays or [])


def add_business_minutes(start_at, minutes, calendar=None):
    if minutes <= 0:
        return start_at
    calendar = calendar or BusinessCalendar.objects.filter(is_active=True).first()
    if not calendar:
        raise ValidationError("تقویم کاری فعال برای محاسبه مهلت تعریف نشده است.")
    try:
        tz = ZoneInfo(calendar.timezone_name)
    except Exception as exc:
        raise ValidationError("منطقه زمانی تقویم کاری معتبر نیست.") from exc
    cursor = timezone.localtime(start_at, tz) if timezone.is_aware(start_at) else timezone.make_aware(start_at, tz)
    remaining = int(minutes)

    for _ in range(3700):
        day = cursor.date()
        if _calendar_is_working_day(calendar, day):
            opening = timezone.make_aware(datetime.combine(day, calendar.start_time), tz)
            closing = timezone.make_aware(datetime.combine(day, calendar.end_time), tz)
            if cursor < opening:
                cursor = opening
            if cursor < closing:
                available = int((closing - cursor).total_seconds() // 60)
                if available >= remaining:
                    return cursor + timedelta(minutes=remaining)
                remaining -= max(available, 0)
        cursor = timezone.make_aware(datetime.combine(day + timedelta(days=1), calendar.start_time), tz)
    raise ValidationError("محاسبه مهلت کاری در بازه مجاز ممکن نشد.")


def resolve_initial_assignee(*, definition, company_id=None, insurer_id=None, line_code=None, owner_user_id=None, exclude_user_id=None):
    insurer_id = insurer_id or _infer_insurer_id(company_id, line_code)
    initial = definition.steps.filter(is_initial=True).first()
    if not initial:
        raise ValidationError("گردش کار مرحله آغازین ندارد.")
    roles = initial.allowed_roles or []
    today = timezone.localdate()
    assignments = RoleAssignment.objects.filter(
        role__in=roles,
        is_active=True,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))

    scope = Q()
    for role in roles:
        role_scope = Q(role=role)
        if role == RoleAssignment.Role.SUBSIDIARY_REP:
            if not company_id:
                continue
            role_scope &= Q(company_id=company_id)
            if line_code:
                role_scope &= Q(line_code__in=[line_code, "*"])
        elif role == RoleAssignment.Role.INSURER_REP:
            if not insurer_id:
                continue
            role_scope &= Q(insurer_id=insurer_id)
        elif role == RoleAssignment.Role.INSURANCE_SPECIALIST:
            if not line_code:
                continue
            role_scope &= Q(line_code__in=[line_code, "*"])
        elif role == RoleAssignment.Role.INSURED_PERSON:
            if not owner_user_id:
                continue
            role_scope &= Q(user_id=owner_user_id)
        scope |= role_scope
    if not scope.children:
        raise ValidationError("برای محدوده این پرونده، نقش گیرنده قابل تخصیص نیست.")
    candidates = User.objects.filter(
        pk__in=assignments.filter(scope).values("user_id"),
        is_active=True,
    )
    if exclude_user_id:
        candidates = candidates.exclude(pk=exclude_user_id)
    candidate = candidates.order_by("pk").first()
    if candidate:
        return candidate
    raise ValidationError("برای مرحله آغازین گردش کار، گیرنده‌ای با انتصاب معتبر در محدوده پرونده پیدا نشد.")


def _validate_recipient(user, roles, *, scope):
    if has_global_access(user):
        return
    if not _has_any_role(user, roles, **scope):
        raise PermissionDenied("گیرنده انتخاب‌شده انتصاب معتبر و هم‌محدوده با پرونده در نقش مجاز این مرحله ندارد.")


def _validate_actor(case, actor, roles, *, scope):
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if has_global_access(actor):
        return
    if case.current_assignee_id != actor.pk:
        raise PermissionDenied("مسئولیت این مرحله به حساب شما واگذار نشده است.")
    if not _has_any_role(actor, roles, **scope):
        raise PermissionDenied("نقش فعال شما برای اقدام در محدوده این پرونده مجاز نیست.")


@transaction.atomic
def start_workflow(*, obj, code, actor, assignee, calendar=None, note=""):
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("شروع گردش کار فقط توسط حساب فعال مجاز است.")
    definition = WorkflowDefinition.objects.filter(code=code, is_active=True).order_by("-version").first()
    if not definition:
        raise ValidationError(f"گردش کار فعال با کد {code} تعریف نشده است.")
    initial = definition.steps.filter(is_initial=True).first()
    if not initial:
        raise ValidationError("گردش کار مرحله آغازین ندارد.")
    scope = _scope_for_object(obj)
    _validate_recipient(assignee, initial.allowed_roles, scope=scope)
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    case, created = WorkflowCase.objects.get_or_create(
        definition=definition,
        content_type=content_type,
        object_id=str(obj.pk),
        defaults={
            "current_step": initial,
            "current_assignee": assignee,
            "status": WorkflowCase.Status.OPEN,
        },
    )
    if not created:
        raise ValidationError("برای این رکورد، پرونده‌ای از همین نسخه گردش کار وجود دارد.")
    _sync_domain_status(obj, step_code=initial.code)
    if initial.sla_minutes:
        case.sla_due_at = add_business_minutes(case.opened_at, initial.sla_minutes, calendar)
        case.save(update_fields=["sla_due_at"])
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=WorkflowEvent.EventType.STARTED,
        to_step=initial,
        to_assignee=assignee,
        note=note,
        sent_at=timezone.now(),
    )
    return case


@transaction.atomic
def mark_case_opened(*, case_id, actor):
    case = WorkflowCase.objects.select_for_update().get(pk=case_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if case.is_locked or case.status in {WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED}:
        return case
    if not has_global_access(actor) and case.current_assignee_id != actor.pk:
        raise PermissionDenied
    now = timezone.now()
    if not case.first_viewed_at:
        case.first_viewed_at = now
        case.save(update_fields=["first_viewed_at"])
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=WorkflowEvent.EventType.OPENED,
        from_step=case.current_step,
        to_step=case.current_step,
        from_assignee=case.current_assignee,
        to_assignee=case.current_assignee,
        opened_at=now,
        sent_at=now,
    )
    return case


@transaction.atomic
def acknowledge_case(*, case_id, actor, note=""):
    case = WorkflowCase.objects.select_for_update().get(pk=case_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if case.is_locked or (not has_global_access(actor) and case.current_assignee_id != actor.pk):
        raise PermissionDenied
    if not case.current_step or not case.current_step.requires_acknowledgement:
        raise PermissionDenied("تأیید رسمی مشاهده در این مرحله فعال نشده است.")
    if not has_global_access(actor) and not _has_any_role(
        actor, case.current_step.allowed_roles, **_scope_for_object(case.content_object)
    ):
        raise PermissionDenied("نقش شما برای تأیید مشاهده در این محدوده مجاز نیست.")
    now = timezone.now()
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=WorkflowEvent.EventType.ACKNOWLEDGED,
        from_step=case.current_step,
        to_step=case.current_step,
        from_assignee=case.current_assignee,
        to_assignee=case.current_assignee,
        acknowledged_at=now,
        sent_at=now,
        note=note,
    )
    return case


@transaction.atomic
def transition_case(*, case_id, actor, action_code, recipient=None, note="", calendar=None):
    case = WorkflowCase.objects.select_for_update().select_related(
        "definition", "current_step", "current_assignee"
    ).get(pk=case_id)
    if case.is_locked or case.status in {WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED}:
        raise PermissionDenied("پرونده بسته یا قفل نهایی شده است.")
    try:
        transition = WorkflowTransition.objects.select_related("source_step", "target_step").get(
            definition=case.definition,
            source_step=case.current_step,
            action_code=action_code,
        )
    except WorkflowTransition.DoesNotExist:
        raise PermissionDenied("این اقدام در مرحله جاری تعریف نشده است.")
    scope = _scope_for_object(case.content_object)
    _validate_actor(case, actor, transition.allowed_roles or case.current_step.allowed_roles, scope=scope)
    if (
        transition.closes_case
        and not has_global_access(actor)
        and scope.get("insurer_id")
        and has_role(
            actor,
            RoleAssignment.Role.INSURER_REP,
            insurer_id=scope["insurer_id"],
        )
    ):
        raise PermissionDenied(
            "نماینده بیمه‌گر مجاز به بستن نهایی پرونده نیست؛ پرونده باید به اداره بیمه ارجاع شود."
        )
    if transition.requires_note and not note.strip():
        raise ValidationError({"note": "برای این اقدام درج توضیحات الزامی است."})
    if transition.is_return and not case.current_step.allow_return:
        raise PermissionDenied("بازگشت از این مرحله مجاز نیست.")

    old_step = case.current_step
    old_assignee = case.current_assignee
    now = timezone.now()

    if transition.closes_case:
        if recipient is not None:
            raise ValidationError("برای اقدام نهایی نباید گیرنده تعیین شود.")
        case.current_step = None
        case.current_assignee = None
        case.status = WorkflowCase.Status.CLOSED
        case.closed_at = now
        event_type = WorkflowEvent.EventType.RETURNED if transition.is_return else WorkflowEvent.EventType.ACTION
    else:
        if transition.target_step is None:
            raise ValidationError("مرحله مقصد برای این اقدام مشخص نشده است.")
        target = recipient or actor
        allowed_recipients = transition.recipient_roles or transition.target_step.allowed_roles
        _validate_recipient(target, allowed_recipients, scope=scope)
        _validate_recipient(target, transition.target_step.allowed_roles, scope=scope)
        case.current_step = transition.target_step
        case.current_assignee = target
        case.status = WorkflowCase.Status.WAITING
        case.closed_at = None
        event_type = WorkflowEvent.EventType.RETURNED if transition.is_return else WorkflowEvent.EventType.REFERRED

    if case.current_step and case.current_step.sla_minutes:
        case.sla_due_at = add_business_minutes(now, case.current_step.sla_minutes, calendar)
    else:
        case.sla_due_at = None
    if not case.first_action_at:
        case.first_action_at = now
    case.save(update_fields=[
        "current_step", "current_assignee", "status", "closed_at",
        "sla_due_at", "first_action_at",
    ])
    _sync_domain_status(
        case.content_object,
        step_code=case.current_step.code if case.current_step else None,
        closed=transition.closes_case,
    )
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=event_type,
        action_code=transition.action_code,
        from_step=old_step,
        to_step=case.current_step,
        from_assignee=old_assignee,
        to_assignee=case.current_assignee,
        note=note,
        acted_at=now,
        sent_at=now,
    )
    return case


@transaction.atomic
def set_final_lock(*, case_id, actor, reason):
    if not has_role(actor, RoleAssignment.Role.SYSTEM_ADMIN):
        raise PermissionDenied("قفل نهایی فقط در اختیار مدیر سامانه است.")
    if not reason.strip():
        raise ValidationError({"reason": "ثبت دلیل قفل نهایی الزامی است."})
    case = WorkflowCase.objects.select_for_update().get(pk=case_id)
    if case.is_locked:
        return case
    now = timezone.now()
    case.is_locked = True
    case.status = WorkflowCase.Status.LOCKED
    case.locked_by = actor
    case.save(update_fields=["is_locked", "status", "locked_by"])
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=WorkflowEvent.EventType.LOCKED,
        from_step=case.current_step,
        to_step=case.current_step,
        from_assignee=case.current_assignee,
        to_assignee=case.current_assignee,
        note=reason,
        sent_at=now,
    )
    return case
