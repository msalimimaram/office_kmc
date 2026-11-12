"""Centralized, time-aware authorization helpers.

New code must authorize by active assignments and explicit scope. The legacy
User.role fallback is intentionally limited to accounts that have never had an
assignment; once an account has assignment history, an inactive or expired
assignment must not fall back to the old single-role field.
"""
from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone

from .models import PositionAssignment, RoleAssignment


LEGACY_ROLE_MAP = {
    "system_admin": RoleAssignment.Role.SYSTEM_ADMIN,
    "department_head": RoleAssignment.Role.DEPARTMENT_HEAD,
    "insurance_specialist": RoleAssignment.Role.INSURANCE_SPECIALIST,
    "subsidiary_rep": RoleAssignment.Role.SUBSIDIARY_REP,
    "insurer": RoleAssignment.Role.INSURER_REP,
    "employee": RoleAssignment.Role.INSURED_PERSON,
}

GLOBAL_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DEPARTMENT_HEAD,
}


def _today(on_date: date | None = None) -> date:
    return on_date or timezone.localdate()


def assignment_history(user):
    """Return all assignment rows, including expired/revoked rows."""
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not getattr(user, "pk", None)
    ):
        return RoleAssignment.objects.none()
    return RoleAssignment.objects.filter(user_id=user.pk)


def active_assignments(user, *, on_date: date | None = None):
    """Return assignments valid on the requested local date."""
    today = _today(on_date)
    return assignment_history(user).filter(
        is_active=True,
        valid_from__lte=today,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    )


def active_position_assignments(user, *, on_date: date | None = None):
    """Return the user's currently valid organizational positions."""
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not getattr(user, "pk", None)
    ):
        return PositionAssignment.objects.none()
    today = _today(on_date)
    return PositionAssignment.objects.filter(
        user_id=user.pk,
        is_active=True,
        valid_from__lte=today,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).select_related("unit", "position")


def active_internal_position_assignments(user, *, on_date: date | None = None):
    """Return only currently valid assignments to active internal positions."""
    return active_position_assignments(user, on_date=on_date).filter(
        position__is_active=True,
        unit__is_active=True,
        unit__company__isnull=True,
    )


def has_position_level(
    user, *levels: int, unit_id: int | None = None, on_date: date | None = None
) -> bool:
    """Check a valid organizational position without granting domain roles."""
    if not levels:
        return False
    qs = active_internal_position_assignments(user, on_date=on_date).filter(
        position__level__in=levels,
        line_code__gt="",
    )
    if unit_id is not None:
        qs = qs.filter(unit_id=unit_id)
    return qs.exists()


def is_unit_manager(user, *, on_date: date | None = None) -> bool:
    """Supervisors and responsibles can manage work within their org scope."""
    return has_position_level(
        user,
        PositionAssignment.position.field.related_model.Level.SUPERVISOR,
        PositionAssignment.position.field.related_model.Level.RESPONSIBLE,
        on_date=on_date,
    )


def _legacy_fallback_allowed(user) -> bool:
    # Inactive accounts must not recover scope through legacy role fields.
    # Any assignment history also suppresses legacy fallback after expiry/revocation.
    return (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and not assignment_history(user).exists()
        # Position-only appointments are authorization history too; a stale
        # legacy employee role must not restore access after deactivation.
        and not PositionAssignment.objects.filter(user_id=user.pk).exists()
    )


def _legacy_role(user):
    role = getattr(user, "role", None)
    if role in {"finance", "legal", "auditor"}:
        return None
    return LEGACY_ROLE_MAP.get(role)


def has_role(
    user,
    *roles: str,
    company_id: int | None = None,
    insurer_id: int | None = None,
    line_code: str | None = None,
    on_date: date | None = None,
) -> bool:
    """Check an operational role with optional company, insurer and line scope."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    requested = set(roles)
    if not requested:
        return False

    assignments = active_assignments(user, on_date=on_date).filter(role__in=requested)
    if company_id is not None:
        assignments = assignments.filter(company_id=company_id)
    if insurer_id is not None:
        assignments = assignments.filter(insurer_id=insurer_id)
    if line_code is not None:
        assignments = assignments.filter(Q(line_code="*") | Q(line_code=line_code))
    if assignments.exists():
        return True

    if not _legacy_fallback_allowed(user):
        return False

    legacy = _legacy_role(user)
    if legacy not in requested:
        return False
    if company_id is not None and getattr(user, "company_id", None) != company_id:
        return False
    if insurer_id is not None and getattr(user, "insurer_id", None) != insurer_id:
        return False
    # A legacy specialist has no reliable line assignment. Fail closed whenever
    # a caller asks for a particular insurance line.
    if line_code is not None and legacy == RoleAssignment.Role.INSURANCE_SPECIALIST:
        return False
    if legacy == RoleAssignment.Role.SUBSIDIARY_REP and not getattr(user, "company_id", None):
        return False
    if legacy == RoleAssignment.Role.INSURER_REP and not getattr(user, "insurer_id", None):
        return False
    return True


def has_global_access(user, *, on_date: date | None = None) -> bool:
    return has_role(user, *GLOBAL_ROLES, on_date=on_date)


def is_insurance_staff(user, *, on_date: date | None = None) -> bool:
    return has_role(
        user,
        RoleAssignment.Role.SYSTEM_ADMIN,
        RoleAssignment.Role.DEPARTMENT_HEAD,
        RoleAssignment.Role.INSURANCE_SPECIALIST,
        on_date=on_date,
    )


def company_ids_for(user, *, role: str | None = None, on_date: date | None = None) -> set[int]:
    if has_global_access(user, on_date=on_date):
        return set()
    qs = active_assignments(user, on_date=on_date).filter(company__isnull=False)
    if role:
        qs = qs.filter(role=role)
    ids = set(qs.values_list("company_id", flat=True))
    if not ids and role == RoleAssignment.Role.INSURED_PERSON:
        from organizations.models import PersonEmployment
        today = _today(on_date)
        ids = set(PersonEmployment.objects.filter(person__user_id=user.pk, status=PersonEmployment.Status.ACTIVE).filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today)).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).values_list("company_id", flat=True))
        if ids:
            return ids
    if not ids and _legacy_fallback_allowed(user):
        legacy = _legacy_role(user)
        if legacy == RoleAssignment.Role.SUBSIDIARY_REP and (not role or role == legacy):
            company_id = getattr(user, "company_id", None)
            return {company_id} if company_id else set()
        if legacy == RoleAssignment.Role.INSURED_PERSON and (not role or role == legacy):
            company_id = getattr(user, "company_id", None)
            return {company_id} if company_id else set()
    return ids


def insurer_ids_for(user, *, on_date: date | None = None) -> set[int]:
    if has_global_access(user, on_date=on_date):
        return set()
    ids = set(
        active_assignments(user, on_date=on_date)
        .filter(role=RoleAssignment.Role.INSURER_REP, insurer__isnull=False)
        .values_list("insurer_id", flat=True)
    )
    if not ids and _legacy_fallback_allowed(user) and _legacy_role(user) == RoleAssignment.Role.INSURER_REP:
        insurer_id = getattr(user, "insurer_id", None)
        return {insurer_id} if insurer_id else set()
    return ids


def line_codes_for(user, *, role: str | None = None, on_date: date | None = None) -> set[str]:
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return set()
    qs = active_assignments(user, on_date=on_date)
    if role:
        qs = qs.filter(role=role)
    values = set(qs.exclude(line_code="").values_list("line_code", flat=True))
    if (
        not values
        and _legacy_fallback_allowed(user)
        and _legacy_role(user) == RoleAssignment.Role.SUBSIDIARY_REP
        and role in (None, RoleAssignment.Role.SUBSIDIARY_REP)
    ):
        # Compatibility for pre-assignment accounts: their old single-role
        # record had company scope but no line dimension. Treat only this
        # legacy-only case as an overall company representative; once any
        # assignment history exists, an explicit '*' or line is required.
        return {"*"}
    return values


def has_line_access(user, line_code: str, *, on_date: date | None = None) -> bool:
    if has_global_access(user, on_date=on_date):
        return True
    return has_role(
        user,
        RoleAssignment.Role.INSURANCE_SPECIALIST,
        RoleAssignment.Role.SUBSIDIARY_REP,
        line_code=line_code,
        on_date=on_date,
    )


def is_company_representative(user, company_id: int, *, line_code: str | None = None) -> bool:
    return has_role(
        user,
        RoleAssignment.Role.SUBSIDIARY_REP,
        company_id=company_id,
        line_code=line_code,
    )


def is_insurer_representative(user, insurer_id: int) -> bool:
    return has_role(user, RoleAssignment.Role.INSURER_REP, insurer_id=insurer_id)


def has_assignment_history(user) -> bool:
    return assignment_history(user).exists()
