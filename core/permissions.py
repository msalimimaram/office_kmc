from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from accounts.access import (
    active_assignments,
    company_ids_for,
    has_global_access,
    has_role,
    insurer_ids_for,
    line_codes_for,
)
from accounts.models import RoleAssignment
from django.utils import timezone


PRIVILEGED = {"system_admin", "department_head"}
INSURANCE_STAFF = PRIVILEGED | {"insurance_specialist"}


def role_required(*roles):
    """Compatibility decorator backed by time-valid operational assignments."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied("شما مجوز دسترسی به این بخش را ندارید.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _has_insured_identity(user):
    """Check the canonical person link first, then legacy national-id mapping."""
    from organizations.models import Person

    return Person.objects.filter(
        Q(user_id=user.pk) | Q(dependents__user_id=user.pk)
    ).exists() or bool(getattr(user, "national_id", ""))


def _insured_claim_filter(user):
    from claims.models import Claim

    if hasattr(user, "person_record"):
        person_id = user.person_record.pk
        return Q(person_id=person_id) | Q(person__employee_id=person_id)
    national_id = getattr(user, "national_id", "")
    if not national_id:
        return Q(pk__in=[])
    # Legacy-only fallback; the global Person.national_id uniqueness migration
    # makes this lookup unambiguous after migration 0002.
    return Q(person__national_id=national_id) | Q(person__employee__national_id=national_id)


def scoped_claims_for(user):
    """Union the claim scopes of all active roles held by the user."""
    from claims.models import Claim

    qs = Claim.objects.select_related(
        "person", "person__company", "person__employee", "contract", "insurer"
    )
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if has_global_access(user):
        return qs

    allowed = Q(pk__in=[])

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        # Historical claims remain visible to the company recorded at service
        # time. The person's current company also receives permitted history.
        today = timezone.localdate()
        current_employment_people = (
            __import__("organizations.models", fromlist=["PersonEmployment"]).PersonEmployment.objects.filter(
                company_id__in=company_ids,
                status="active",
            )
            .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .values_list("person_id", flat=True)
        )
        legacy_people = (
            __import__("organizations.models", fromlist=["Person"]).Person.objects.filter(
                company_id__in=company_ids,
                employments__isnull=True,
            ).values_list("pk", flat=True)
        )
        allowed |= (
            Q(company_snapshot_id__in=company_ids)
            | Q(company_snapshot__isnull=True, person__company_id__in=company_ids)
            | Q(person_id__in=current_employment_people)
            | Q(primary_insured_id__in=current_employment_people)
            | Q(person_id__in=legacy_people)
            | Q(primary_insured_id__in=legacy_people)
        )

    insurer_ids = insurer_ids_for(user)
    if insurer_ids:
        allowed |= (
            Q(insurer_id__in=insurer_ids)
            | Q(insurer__isnull=True, contract__insurer_id__in=insurer_ids)
        )

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        line_codes = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if "*" in line_codes:
            allowed |= Q(contract__isnull=False)
        else:
            concrete_lines = {code for code in line_codes if code}
            if concrete_lines:
                allowed |= Q(contract__line__in=concrete_lines)

    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        allowed |= _insured_claim_filter(user)

    return qs.filter(allowed).distinct()


def scoped_requests_for(user):
    """Union the request scopes of all active roles held by the user."""
    from requests_portal.models import ServiceRequest

    qs = ServiceRequest.objects.select_related(
        "submitted_by", "company", "person", "assigned_to"
    )
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if has_global_access(user):
        return qs

    allowed = Q(pk__in=[])

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        allowed |= Q(company_id__in=company_ids, is_confidential=False)

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        # Requests reach a specialist through an explicit workflow assignment.
        # There is no shared unassigned queue: the representative/manager chooses
        # the authorized recipient and the workflow transfers ownership.
        allowed |= Q(assigned_to_id=user.pk, is_confidential=False)

    if has_role(user, RoleAssignment.Role.INSURER_REP):
        # Insurer-side access is limited to work explicitly referred to this user.
        allowed |= Q(assigned_to_id=user.pk, is_confidential=False)

    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        allowed |= Q(submitted_by_id=user.pk)

    return qs.filter(allowed).distinct()


def can_view_claim(user, claim):
    return scoped_claims_for(user).filter(pk=claim.pk).exists()


def can_view_request(user, item):
    return scoped_requests_for(user).filter(pk=item.pk).exists()


def can_process_request(user, item):
    if has_global_access(user):
        return True
    if item.is_confidential:
        return False
    return (
        has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
    ) and item.assigned_to_id == user.pk


def can_edit_claim(user, claim):
    if has_global_access(user):
        return True
    # Insurer representatives submit source data; accepted claim changes require staff approval.
    return can_view_claim(user, claim) and has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)


def can_decide_claim(user, claim):
    if has_global_access(user):
        return True
    return can_view_claim(user, claim) and has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)


def can_edit_iban(user, person):
    # Sensitive financial attributes must be changed through an approved request.
    if has_global_access(user):
        return True
    return has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)


def require_object_access(allowed, message="شما مجوز دسترسی به این رکورد را ندارید."):
    if not allowed:
        raise PermissionDenied(message)
