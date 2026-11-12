from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone

from accounts.access import (
    active_assignments, active_position_assignments,
    has_global_access, has_role,
)
from accounts.models import PositionAssignment, RoleAssignment
from .models import (
    BusinessCalendar, WorkflowCase, WorkflowDefinition, WorkflowEvent,
    WorkflowStep, WorkflowTransition,
)


User = get_user_model()


HEALTH_REQUEST_KINDS = {
    "medical_assistance", "anonymous_plan", "excess_coverage",
    "identity_change", "iban_change",
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


def _has_any_position(user, position_levels, *, line_code=None):
    """Check a valid internal position within the workflow's line scope.

    A blank line assignment is not treated as an all-lines grant. Cross-line
    authority must be explicit through line_code='*'.
    """
    if not position_levels or not user or not user.is_authenticated or not user.is_active:
        return False
    qs = active_position_assignments(user).filter(
        position__level__in=position_levels,
        unit__company__isnull=True,
    )
    if line_code:
        qs = qs.filter(Q(line_code=line_code) | Q(line_code="*"))
    else:
        qs = qs.filter(line_code="*")
    return qs.exists()


def _has_any_role(
    user, roles, *, company_id=None, insurer_id=None, line_code=None,
    owner_user_id=None, position_levels=(),
):
    if (
        not user or not user.is_authenticated or not user.is_active
        or (not roles and not position_levels)
    ):
        return False

    assignments = active_assignments(user)
    for role in roles:
        # A scoped role must never become an unscoped role because an object
        # lacks the corresponding scope field.
        if role == RoleAssignment.Role.SUBSIDIARY_REP:
            if company_id is None:
                continue
            scoped = assignments.filter(role=role, company_id=company_id)
            if line_code:
                scoped = scoped.filter(Q(line_code="*") | Q(line_code=line_code))
            if scoped.exists():
                return True
            continue
        if role == RoleAssignment.Role.INSURER_REP:
            if insurer_id is None:
                continue
            if assignments.filter(role=role, insurer_id=insurer_id).exists():
                return True
            continue
        if role == RoleAssignment.Role.INSURANCE_SPECIALIST:
            if not line_code:
                continue
            if assignments.filter(role=role).filter(
                Q(line_code="*") | Q(line_code=line_code)
            ).exists():
                return True
            continue
        if role == RoleAssignment.Role.INSURED_PERSON:
            if owner_user_id == user.pk and has_role(user, role):
                return True
            continue

        # A Django superuser is a system administrator, not automatically a
        # specialist, company representative, or insurer representative.
        if getattr(user, "is_superuser", False):
            if assignments.filter(role=role).exists():
                return True
            continue
        if has_role(user, role):
            return True
    return _has_any_position(user, position_levels, line_code=line_code)


def _position_assignment_queryset(user, position_levels, *, line_code=None):
    """Active, internal, line-matched assignments that can authorize a workflow step."""
    if not position_levels or not user or not user.is_authenticated or not user.is_active:
        return PositionAssignment.objects.none()
    qs = active_position_assignments(user).filter(
        position__level__in=position_levels,
        position__is_active=True,
        unit__is_active=True,
        unit__company__isnull=True,
    )
    if line_code:
        qs = qs.filter(Q(line_code=line_code) | Q(line_code="*"))
    else:
        qs = qs.filter(line_code="*")
    return qs.order_by("position__level", "unit_id", "pk")


def _resolve_position_assignment(user, position_levels, *, line_code=None):
    return _position_assignment_queryset(
        user, position_levels, line_code=line_code
    ).first()


def _position_assignment_is_current(
    assignment_id, user, position_levels, *, line_code=None
):
    if not assignment_id:
        return False
    return _position_assignment_queryset(
        user, position_levels, line_code=line_code
    ).filter(pk=assignment_id).exists()


def _has_operational_role(user, roles, *, scope):
    """Check only role grants; do not mix a position grant into this result."""
    return _has_any_role(user, roles, **scope)


def _current_position_assignment(case, actor, position_levels=(), *, line_code=None):
    """Resolve the exact active position row recorded as this case's owner grant."""
    if not case.current_position_assignment_id:
        return None
    return _position_assignment_queryset(
        actor, position_levels, line_code=line_code
    ).filter(pk=case.current_position_assignment_id).select_related(
        "position", "unit"
    ).first()


def _case_actor_authorized(case, actor, roles, *, position_levels=(), scope):
    """Validate the exact grant recorded when this user became current owner."""
    if case.current_position_assignment_id:
        assignment = _current_position_assignment(
            case,
            actor,
            case.current_step.allowed_position_levels if case.current_step_id else [],
            line_code=scope.get("line_code"),
        )
        if assignment is None:
            return False
        if _has_operational_role(actor, roles, scope=scope):
            return True
        return assignment.position.level in set(position_levels or [])
    return _has_any_role(
        actor, roles, position_levels=position_levels, **scope
    )




def _sync_domain_assignee(obj, assignee):
    """Synchronize an opted-in domain adapter with WorkflowCase ownership."""
    if obj is None:
        return
    adapter = getattr(obj, "sync_workflow_assignee", None)
    if callable(adapter):
        adapter(assignee=assignee)


def _sync_domain_status(obj, *, step_code=None, closed=False, actor=None):
    """Synchronize an opted-in domain adapter or matching status choice."""
    if obj is None:
        return
    adapter = getattr(obj, "sync_workflow_status", None)
    if callable(adapter):
        adapter(step_code=step_code, closed=closed, actor=actor)
        return
    if not hasattr(obj, "status"):
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


def resolve_initial_assignee(*, definition, company_id=None, insurer_id=None, line_code=None, owner_user_id=None, exclude_user_id=None, obj=None, item_type=None, return_delegation=False):
    # When the caller supplies a domain object, derive any missing authorization
    # scope from that object and its known parent relations. Explicit arguments
    # remain authoritative, while object-only calls cannot accidentally become
    # unscoped for company, insurer, specialist, or insured-person assignments.
    if obj is not None:
        object_scope = _scope_for_object(obj)
        company_id = company_id or object_scope["company_id"]
        insurer_id = insurer_id or object_scope["insurer_id"]
        line_code = line_code or object_scope["line_code"]
        owner_user_id = owner_user_id or object_scope["owner_user_id"]
    insurer_id = insurer_id or _infer_insurer_id(company_id, line_code)
    initial = definition.steps.filter(is_initial=True).first()
    if not initial:
        raise ValidationError("گردش کار مرحله آغازین ندارد.")
    roles = initial.allowed_roles or []
    position_levels = initial.allowed_position_levels or []
    if item_type is None:
        item_type = str(
            getattr(obj, "change_type", None)
            or getattr(obj, "kind", None)
            or ""
        )
    from delegations.services import find_matching_delegation
    delegation = find_matching_delegation(
        workflow_code=definition.code,
        item_type=item_type,
        company_id=company_id,
        insurer_id=insurer_id,
        line_code=line_code,
    )
    if delegation is not None:
        if (
            delegation.delegate_role not in set(roles)
            and delegation.delegate_role != RoleAssignment.Role.INSURANCE_SPECIALIST
        ):
            raise ValidationError("نقش گیرنده تفویض برای مرحله آغازین این گردش‌کار مجاز نیست.")
        if exclude_user_id and delegation.delegate_to_id == exclude_user_id:
            raise ValidationError("گیرنده تفویض‌شده نمی‌تواند درخواست خود را دریافت کند.")
        result = (delegation.delegate_to, delegation)
        return result if return_delegation else delegation.delegate_to

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
    if not scope.children and not position_levels:
        raise ValidationError("برای محدوده این پرونده، نقش یا سمت گیرنده قابل تخصیص نیست.")
    # The order of roles in the published initial step is the routing
    # priority (for example, specialist before head/system admin). Only after
    # selecting the highest-priority role do we balance between its eligible
    # assignees by current open workload, then stable primary key.
    eligible_rows = list(
        assignments.filter(scope).values_list("role", "user_id").distinct()
    ) if roles and scope.children else []
    eligible_by_role = {
        role: {user_id for assigned_role, user_id in eligible_rows if assigned_role == role}
        for role in roles
    }
    for role in roles:
        user_ids = eligible_by_role.get(role, set())
        if exclude_user_id:
            user_ids.discard(exclude_user_id)
        if not user_ids:
            continue
        candidate = User.objects.filter(
            pk__in=user_ids,
            is_active=True,
        ).annotate(
            active_workload=Count(
                "workflow_cases",
                filter=Q(workflow_cases__status__in=[
                    WorkflowCase.Status.OPEN,
                    WorkflowCase.Status.WAITING,
                ]),
                distinct=True,
            )
        ).order_by("active_workload", "pk").first()
        if candidate:
            return (candidate, None) if return_delegation else candidate

    # Position levels are evaluated after explicitly ordered operational roles.
    # Each position must be active, belong to an internal unit, and match the
    # business line; all-line authority requires an explicit '*' assignment.
    for level in position_levels:
        position_user_ids = active_position_assignments_for_level(
            level, line_code=line_code
        )
        if exclude_user_id:
            position_user_ids = position_user_ids.exclude(user_id=exclude_user_id)
        candidate = User.objects.filter(
            pk__in=position_user_ids.values("user_id"),
            is_active=True,
        ).annotate(
            active_workload=Count(
                "workflow_cases",
                filter=Q(workflow_cases__status__in=[
                    WorkflowCase.Status.OPEN,
                    WorkflowCase.Status.WAITING,
                ]),
                distinct=True,
            )
        ).order_by("active_workload", "pk").first()
        if candidate:
            return (candidate, None) if return_delegation else candidate

    raise ValidationError("برای مرحله آغازین گردش کار، گیرنده‌ای با انتصاب معتبر در محدوده پرونده پیدا نشد.")


def active_position_assignments_for_level(level, *, line_code=None):
    """Query active internal position assignments eligible for one workflow level."""
    today = timezone.localdate()
    qs = PositionAssignment.objects.filter(
        position__level=level,
        position__is_active=True,
        unit__is_active=True,
        unit__company__isnull=True,
        is_active=True,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    if line_code:
        return qs.filter(Q(line_code=line_code) | Q(line_code="*"))
    return qs.filter(line_code="*")


def _validate_recipient(user, roles, *, scope, position_levels=()):
    if _has_operational_role(user, roles, scope=scope):
        return None
    position_assignment = _resolve_position_assignment(
        user,
        position_levels,
        line_code=scope.get("line_code"),
    )
    if position_assignment:
        return position_assignment
    raise PermissionDenied("گیرنده انتخاب‌شده انتصاب معتبر و هم‌محدوده با پرونده در نقش یا سمت مجاز این مرحله ندارد.")


def is_delegated_assignee(case, user):
    """True only while the user holds a live, matching delegation for this case."""
    if not case or not user or not getattr(user, "is_authenticated", False):
        return False
    delegation = getattr(case, "delegation", None)
    if not delegation or delegation.delegate_to_id != user.pk:
        return False
    from delegations.services import delegation_matches, find_matching_delegation
    scope = _scope_for_object(case.content_object)
    item_type = str(
        getattr(case.content_object, "change_type", None)
        or getattr(case.content_object, "kind", None)
        or ""
    )
    try:
        # An ambiguous rule set must fail closed until a manager resolves it.
        find_matching_delegation(
            workflow_code=case.definition.code,
            item_type=item_type,
            company_id=scope.get("company_id"),
            insurer_id=scope.get("insurer_id"),
            line_code=scope.get("line_code"),
        )
    except ValidationError:
        return False
    return delegation_matches(
        delegation,
        workflow_code=case.definition.code,
        item_type=item_type,
        scope=scope,
    )


def _validate_actor(case, actor, roles, *, scope, position_levels=()):
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if case.current_assignee_id != actor.pk:
        raise PermissionDenied("مسئولیت اقدام این مرحله به حساب شما واگذار نشده است.")
    if case.delegation_id and not is_delegated_assignee(case, actor):
        raise PermissionDenied("اعتبار تفویض این پرونده پایان یافته یا لغو شده است.")
    if not _case_actor_authorized(
        case, actor, roles, position_levels=position_levels, scope=scope
    ):
        raise PermissionDenied("نقش یا انتصاب سمت ثبت‌شده برای مسئول جاری پرونده معتبر نیست.")


def _workflow_owner_candidates(obj):
    """Return the people who can reasonably be notified about this workflow item."""
    label = obj._meta.label_lower
    candidates = []

    if label == "requests_portal.servicerequest":
        if getattr(obj, "submitted_by_id", None):
            candidates.append(obj.submitted_by)
    elif label == "organizations.personchangerequest":
        if getattr(obj, "requested_by_id", None):
            candidates.append(obj.requested_by)
    elif label == "claims.claimobjection":
        if getattr(obj, "submitted_by_id", None):
            candidates.append(obj.submitted_by)
        claim = obj.claim
        for person in (claim.primary_insured, claim.person):
            if person and person.user_id:
                candidates.append(person.user)
            employee = person.employee if person and person.employee_id else None
            if employee and employee.user_id:
                candidates.append(employee.user)
    elif label == "claims.claim":
        for person in (getattr(obj, "primary_insured", None), obj.person):
            if person and person.user_id:
                candidates.append(person.user)
    elif label == "assets.insuredasset":
        if getattr(obj, "created_by_id", None):
            candidates.append(obj.created_by)
    elif label == "insurance.contractrevision":
        if getattr(obj, "created_by_id", None):
            candidates.append(obj.created_by)

    person = getattr(obj, "person", None)
    if person is not None:
        if person.user_id:
            candidates.append(person.user)
        employee = person.employee if person.employee_id else None
        if employee and employee.user_id:
            candidates.append(employee.user)

    # Keep insertion order while preventing duplicate notifications.
    unique = {}
    for candidate in candidates:
        if candidate and candidate.is_active:
            unique[candidate.pk] = candidate
    return list(unique.values())


def _workflow_owner_can_view(obj, recipient, case):
    """Resolve the real domain detail URL and verify its normal visibility scope."""
    from django.urls import reverse

    label = obj._meta.label_lower
    if label == "requests_portal.servicerequest":
        from core.permissions import can_view_request
        return (
            reverse("request_detail", args=[obj.pk])
            if can_view_request(recipient, obj) else ""
        )
    if label == "organizations.personchangerequest":
        allowed_role = any(
            has_role(recipient, role)
            for role in (
                RoleAssignment.Role.INSURED_PERSON,
                RoleAssignment.Role.SUBSIDIARY_REP,
                RoleAssignment.Role.INSURER_REP,
                RoleAssignment.Role.INSURANCE_SPECIALIST,
            )
        )
        person_owner = bool(
            obj.person.user_id == recipient.pk
            or (
                obj.person.employee_id
                and obj.person.employee.user_id == recipient.pk
            )
        )
        if allowed_role and (
            obj.requested_by_id == recipient.pk
            or person_owner
            or case.current_assignee_id == recipient.pk
            or has_global_access(recipient)
        ):
            return reverse("person_change_detail", args=[obj.pk])
        return ""
    if label in {"claims.claim", "claims.claimobjection"}:
        from core.permissions import can_view_claim
        claim = obj if label == "claims.claim" else obj.claim
        return reverse("claim_detail", args=[claim.pk]) if can_view_claim(recipient, claim) else ""
    if label == "assets.insuredasset":
        from assets.views import _asset_scope
        return (
            reverse("asset_detail", args=[obj.pk])
            if _asset_scope(recipient).filter(pk=obj.pk).exists() else ""
        )
    if label == "insurance.contractrevision":
        from insurance.views import _contract_scope
        return (
            reverse("contract_detail", args=[obj.contract_id])
            if _contract_scope(recipient).filter(pk=obj.contract_id).exists() else ""
        )
    return ""


def _notify_workflow_owners(case, actor, *, started=False, closed=False):
    """Notify only request owners who can open the corresponding domain record."""
    from accounts.models import UserNotification

    obj = case.content_object
    if obj is None:
        return
    title = (
        "رسیدگی به درخواست شما پایان یافت"
        if closed else
        "درخواست شما در سامانه ثبت شد"
        if started else
        "وضعیت درخواست شما به‌روزرسانی شد"
    )
    if closed:
        body = "رسیدگی به درخواست شما به پایان رسیده است. برای مشاهده نتیجه، پرونده را باز کنید."
    elif started:
        body = "درخواست شما ثبت شده و در مسیر رسیدگی قرار گرفته است."
    else:
        step_title = case.current_step.title if case.current_step else "مرحله نهایی"
        body = f"درخواست شما به مرحله «{step_title}» منتقل شده است."

    for recipient in _workflow_owner_candidates(obj):
        if recipient.pk == getattr(actor, "pk", None):
            continue
        notification_role = (
            has_global_access(recipient)
            or has_role(recipient, RoleAssignment.Role.INSURANCE_SPECIALIST)
            or has_role(recipient, RoleAssignment.Role.INSURED_PERSON)
            or has_role(recipient, RoleAssignment.Role.SUBSIDIARY_REP)
            or has_role(recipient, RoleAssignment.Role.INSURER_REP)
        )
        if not notification_role:
            continue
        target_url = _workflow_owner_can_view(obj, recipient, case)
        if not target_url:
            continue
        UserNotification.objects.create(
            recipient=recipient,
            actor=actor,
            title=title,
            body=body,
            target_url=target_url,
        )


@transaction.atomic
def start_workflow(*, obj, code, actor, assignee, calendar=None, note="", delegation=None):
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("شروع گردش کار فقط توسط حساب فعال مجاز است.")
    definition = WorkflowDefinition.objects.filter(code=code, is_active=True).order_by("-version").first()
    if not definition:
        raise ValidationError(f"گردش کار فعال با کد {code} تعریف نشده است.")
    initial = definition.steps.filter(is_initial=True).first()
    if not initial:
        raise ValidationError("گردش کار مرحله آغازین ندارد.")
    scope = _scope_for_object(obj)
    position_assignment = None
    if delegation is not None:
        from delegations.services import delegation_matches
        item_type = str(
            getattr(obj, "change_type", None)
            or getattr(obj, "kind", None)
            or ""
        )
        if delegation.delegate_to_id != assignee.pk or not delegation_matches(
            delegation,
            workflow_code=code,
            item_type=item_type,
            scope=scope,
        ):
            raise PermissionDenied("تفویض انتخاب‌شده برای این پرونده معتبر یا فعال نیست.")
    else:
        position_assignment = _validate_recipient(
            assignee,
            initial.allowed_roles,
            position_levels=initial.allowed_position_levels,
            scope=scope,
        )
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    case, created = WorkflowCase.objects.get_or_create(
        definition=definition,
        content_type=content_type,
        object_id=str(obj.pk),
        defaults={
            "current_step": initial,
            "current_assignee": assignee,
            "delegation": delegation,
            "current_position_assignment": position_assignment,
            "status": WorkflowCase.Status.OPEN,
        },
    )
    if not created:
        raise ValidationError("برای این رکورد، پرونده‌ای از همین نسخه گردش کار وجود دارد.")
    _sync_domain_status(obj, step_code=initial.code, actor=actor)
    _sync_domain_assignee(obj, assignee)
    if initial.sla_minutes:
        case.sla_due_at = add_business_minutes(case.opened_at, initial.sla_minutes, calendar)
        case.save(update_fields=["sla_due_at"])
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=WorkflowEvent.EventType.STARTED,
        to_step=initial,
        to_assignee=assignee,
        to_position_assignment=position_assignment,
        note=(note + (" | تفویض‌شده: " + delegation.reason if delegation else ""))[:4000],
        sent_at=timezone.now(),
    )
    _notify_assignee(case, actor, assignee, delegated=delegation is not None)
    _notify_workflow_owners(case, actor, started=True)
    return case


def _notify_assignee(case, actor, assignee, *, delegated=False):
    if not assignee or assignee.pk == getattr(actor, "pk", None):
        return
    from django.urls import reverse
    from accounts.models import UserNotification
    title = "کار جدید به شما تفویض شد" if delegated else "پرونده جدید به شما ارجاع شد"
    body = (
        f"پرونده {case.definition.title} در محدوده مسئولیت شما قرار گرفت."
        if delegated else
        f"پرونده {case.definition.title} برای اقدام به شما ارجاع شد."
    )
    UserNotification.objects.create(
        recipient=assignee,
        actor=actor,
        title=title,
        body=body,
        target_url=reverse("workflow_case_detail", args=[case.pk]),
    )


@transaction.atomic
def mark_case_opened(*, case_id, actor):
    case = WorkflowCase.objects.select_for_update().get(pk=case_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if case.is_locked or case.status in {WorkflowCase.Status.CLOSED, WorkflowCase.Status.COMPLETED}:
        return case
    if case.current_assignee_id != actor.pk:
        raise PermissionDenied("مشاهده عملیاتی این مرحله فقط برای مسئول جاری پرونده ثبت می‌شود.")
    delegated = bool(case.delegation_id and is_delegated_assignee(case, actor))
    if case.delegation_id and not delegated:
        raise PermissionDenied("اعتبار تفویض این پرونده پایان یافته یا لغو شده است.")
    if not delegated and (
        not case.current_step
        or not _case_actor_authorized(
            case,
            actor,
            case.current_step.allowed_roles,
            position_levels=case.current_step.allowed_position_levels,
            scope=_scope_for_object(case.content_object),
        )
    ):
        raise PermissionDenied("انتصاب فعال شما برای مشاهده عملیاتی این مرحله معتبر نیست.")
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
        from_position_assignment=case.current_position_assignment,
        to_position_assignment=case.current_position_assignment,
        opened_at=now,
        sent_at=now,
    )
    return case


@transaction.atomic
def acknowledge_case(*, case_id, actor, note=""):
    case = WorkflowCase.objects.select_for_update().get(pk=case_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    if case.is_locked or case.current_assignee_id != actor.pk:
        raise PermissionDenied("تأیید مشاهده فقط توسط مسئول جاری پرونده مجاز است.")
    if case.delegation_id and not is_delegated_assignee(case, actor):
        raise PermissionDenied("اعتبار تفویض این پرونده پایان یافته یا لغو شده است.")
    if not case.current_step or not case.current_step.requires_acknowledgement:
        raise PermissionDenied("تأیید رسمی مشاهده در این مرحله فعال نشده است.")
    if (
        not is_delegated_assignee(case, actor)
        and not _case_actor_authorized(
            case,
            actor,
            case.current_step.allowed_roles,
            position_levels=case.current_step.allowed_position_levels,
            scope=_scope_for_object(case.content_object),
        )
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
        from_position_assignment=case.current_position_assignment,
        to_position_assignment=case.current_position_assignment,
        acknowledged_at=now,
        sent_at=now,
        note=note,
    )
    return case


@transaction.atomic
def transition_case(*, case_id, actor, action_code, recipient=None, note="", calendar=None):
    case = WorkflowCase.objects.select_for_update().select_related(
        "definition", "current_step", "current_assignee", "delegation"
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
    _validate_actor(
        case,
        actor,
        transition.allowed_roles or case.current_step.allowed_roles,
        position_levels=(
            transition.allowed_position_levels
            or case.current_step.allowed_position_levels
        ),
        scope=scope,
    )
    is_global_business_decider = _has_operational_role(
        actor,
        [RoleAssignment.Role.SYSTEM_ADMIN, RoleAssignment.Role.DEPARTMENT_HEAD],
        scope=scope,
    )
    if (
        transition.closes_case
        and case.definition.code in {"claim_objection", "contract_approval", "contract_termination"}
        and not is_global_business_decider
    ):
        raise PermissionDenied(
            "تصمیم نهایی این فرایند فقط برای رئیس اداره بیمه یا مدیر سامانه مجاز است."
        )
    if (
        transition.closes_case
        and case.definition.code == "person_change"
        and not (
            is_global_business_decider
            or _has_operational_role(
                actor,
                [RoleAssignment.Role.SUBSIDIARY_REP],
                scope=scope,
            )
        )
    ):
        raise PermissionDenied(
            "بستن درخواست اصلاح اطلاعات فقط برای نماینده همان شرکت یا مدیر/رئیس اداره مجاز است."
        )
    if (
        transition.closes_case
        and not is_global_business_decider
        and scope.get("insurer_id")
        and _has_operational_role(
            actor,
            [RoleAssignment.Role.INSURER_REP],
            scope=scope,
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
    old_position_assignment = case.current_position_assignment
    delegation_id = case.delegation_id
    now = timezone.now()

    if transition.closes_case:
        if recipient is not None:
            raise ValidationError("برای اقدام نهایی نباید گیرنده تعیین شود.")
        case.current_step = None
        case.current_assignee = None
        case.delegation = None
        case.current_position_assignment = None
        case.status = WorkflowCase.Status.CLOSED
        case.closed_at = now
        event_type = WorkflowEvent.EventType.RETURNED if transition.is_return else WorkflowEvent.EventType.ACTION
    else:
        if transition.target_step is None:
            raise ValidationError("مرحله مقصد برای این اقدام مشخص نشده است.")
        target = recipient or actor
        allowed_recipients = transition.recipient_roles or transition.target_step.allowed_roles
        allowed_position_recipients = (
            transition.recipient_position_levels
            or transition.target_step.allowed_position_levels
        )
        target_position_assignment = _validate_recipient(
            target,
            allowed_recipients,
            position_levels=allowed_position_recipients,
            scope=scope,
        )
        target_step_position_assignment = _validate_recipient(
            target,
            transition.target_step.allowed_roles,
            position_levels=transition.target_step.allowed_position_levels,
            scope=scope,
        )
        if (
            target_position_assignment
            and target_step_position_assignment
            and target_position_assignment.pk != target_step_position_assignment.pk
        ):
            raise PermissionDenied("انتصاب سمت گیرنده با مرحله مقصد یکسان نیست.")
        # The target step defines the enduring authorization grant. The
        # transition recipient rule is an additional gate, not a substitute
        # for the grant that authorizes the next stage.
        position_assignment = target_step_position_assignment
        case.current_step = transition.target_step
        case.current_assignee = target
        case.current_position_assignment = position_assignment
        if case.delegation_id and case.delegation.delegate_to_id != target.pk:
            case.delegation = None
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
        "current_step", "current_assignee", "delegation", "current_position_assignment",
        "status", "closed_at",
        "sla_due_at", "first_action_at",
    ])
    domain_object = case.content_object
    _sync_domain_status(
        domain_object,
        step_code=old_step.code if transition.closes_case else (
            case.current_step.code if case.current_step else None
        ),
        closed=transition.closes_case,
        actor=actor,
    )
    _sync_domain_assignee(domain_object, case.current_assignee)
    WorkflowEvent.objects.create(
        workflow_case=case,
        actor=actor,
        event_type=event_type,
        action_code=transition.action_code,
        from_step=old_step,
        to_step=case.current_step,
        from_assignee=old_assignee,
        to_assignee=case.current_assignee,
        from_position_assignment=old_position_assignment,
        to_position_assignment=case.current_position_assignment,
        note=note,
        acted_at=now,
        sent_at=now,
        metadata={"delegation_id": delegation_id} if delegation_id else {},
    )
    if case.current_assignee_id and case.current_assignee_id != actor.pk:
        _notify_assignee(case, actor, case.current_assignee, delegated=is_delegated_assignee(case, case.current_assignee))
    _notify_workflow_owners(case, actor, closed=transition.closes_case)
    return case


@transaction.atomic
def set_final_lock(*, case_id, actor, reason):
    if not _has_any_role(actor, [RoleAssignment.Role.SYSTEM_ADMIN]):
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
        from_position_assignment=case.current_position_assignment,
        to_position_assignment=case.current_position_assignment,
        note=reason,
        sent_at=now,
    )
    return case
