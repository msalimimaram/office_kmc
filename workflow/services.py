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


def _has_any_role(user, roles):
    if "*" in roles:
        return user.is_authenticated and user.is_active
    return bool(roles) and any(has_role(user, role) for role in roles)


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
    tz = ZoneInfo(calendar.timezone_name)
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


def _validate_recipient(user, roles):
    if not user or not user.is_active or not _has_any_role(user, roles):
        raise PermissionDenied("گیرنده انتخاب‌شده انتصاب معتبر در نقش مجاز این مرحله ندارد.")


def _validate_actor(case, actor, roles):
    if not actor.is_active:
        raise PermissionDenied
    if has_global_access(actor):
        return
    if case.current_assignee_id != actor.pk:
        raise PermissionDenied("مسئولیت این مرحله به حساب شما واگذار نشده است.")
    if roles and not _has_any_role(actor, roles):
        raise PermissionDenied("نقش فعال شما برای اقدام در این مرحله مجاز نیست.")


@transaction.atomic
def start_workflow(*, obj, code, actor, assignee, calendar=None, note=""):
    definition = WorkflowDefinition.objects.filter(code=code, is_active=True).order_by("-version").first()
    if not definition:
        raise ValidationError(f"گردش کار فعال با کد {code} تعریف نشده است.")
    initial = definition.steps.filter(is_initial=True).first()
    if not initial:
        raise ValidationError("گردش کار مرحله آغازین ندارد.")
    _validate_recipient(assignee, initial.allowed_roles)
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
    if case.is_locked or (not has_global_access(actor) and case.current_assignee_id != actor.pk):
        raise PermissionDenied
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
    transition = WorkflowTransition.objects.select_related("source_step", "target_step").get(
        definition=case.definition,
        source_step=case.current_step,
        action_code=action_code,
    )
    _validate_actor(case, actor, transition.allowed_roles or case.current_step.allowed_roles)
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
        _validate_recipient(target, allowed_recipients)
        if not _has_any_role(target, transition.target_step.allowed_roles):
            raise PermissionDenied("گیرنده در مرحله مقصد مجاز نیست.")
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
