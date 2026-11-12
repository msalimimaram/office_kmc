from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, BigIntegerField
from django.db.models.functions import Cast

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
        from organizations.models import Person, PersonEmployment

        # Historical claims remain visible to the company recorded at service
        # time. The person's current company also receives permitted history.
        today = timezone.localdate()
        current_employment_people = (
            PersonEmployment.objects.filter(
                company_id__in=company_ids,
                status="active",
            )
            .filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .values_list("person_id", flat=True)
        )
        legacy_people = (
            Person.objects.filter(
                company_id__in=company_ids,
                employments__isnull=True,
            ).values_list("pk", flat=True)
        )
        company_scope = (
            # A real employment history lets the current employer see the
            # employee's prior claims. A legacy company pointer alone must not
            # override a conflicting company snapshot on a claim.
            Q(company_snapshot_id__in=company_ids)
            | Q(person_id__in=current_employment_people)
            | Q(primary_insured_id__in=current_employment_people)
            | Q(company_snapshot__isnull=True, person_id__in=legacy_people)
            | Q(company_snapshot__isnull=True, primary_insured_id__in=legacy_people)
        )
        representative_lines = line_codes_for(
            user, role=RoleAssignment.Role.SUBSIDIARY_REP
        )
        if "*" in representative_lines:
            allowed |= company_scope
        elif representative_lines:
            # The claim's contract is the authoritative source of insurance line.
            # Claims without a contract cannot be safely exposed to a line-limited
            # representative because no reliable line can be inferred.
            allowed |= company_scope & Q(contract__line__in=representative_lines)

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
    """Union request visibility scopes, using WorkflowCase for routed work."""
    from django.contrib.contenttypes.models import ContentType
    from requests_portal.models import ServiceRequest
    from workflow.models import WorkflowCase, WorkflowEvent

    qs = ServiceRequest.objects.select_related(
        "submitted_by", "company", "person", "assigned_to"
    )
    if not getattr(user, "is_authenticated", False):
        return qs.none()
    if has_global_access(user):
        return qs

    allowed = Q(pk__in=[])

    content_type = ContentType.objects.get_for_model(
        ServiceRequest, for_concrete_model=False
    )
    active_workflow_request_ids = WorkflowCase.objects.filter(
        content_type=content_type,
        current_assignee_id=user.pk,
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        is_locked=False,
    ).annotate(domain_pk=Cast("object_id", BigIntegerField())).values("domain_pk")
    confidential_assigned_scope = ServiceRequest.objects.filter(
        pk__in=active_workflow_request_ids,
        is_confidential=True,
    )

    health_request_kinds = {
        ServiceRequest.Kind.MEDICAL_ASSISTANCE,
        ServiceRequest.Kind.ANONYMOUS_PLAN,
        ServiceRequest.Kind.EXCESS_COVERAGE,
        ServiceRequest.Kind.IDENTITY_CHANGE,
        ServiceRequest.Kind.IBAN_CHANGE,
        ServiceRequest.Kind.ADD_COVERAGE,
        ServiceRequest.Kind.REMOVE_COVERAGE,
        ServiceRequest.Kind.BASE_INSURANCE_WAIVER,
    }

    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        company_scope = Q(company_id__in=company_ids, is_confidential=False)
        representative_lines = line_codes_for(
            user, role=RoleAssignment.Role.SUBSIDIARY_REP
        )
        if "*" in representative_lines:
            allowed |= company_scope
        elif "health" in representative_lines:
            # This model has no direct contract/line link yet. Only request
            # kinds with an unambiguous health line are visible to this rep.
            allowed |= company_scope & Q(kind__in=health_request_kinds)
        if "*" in representative_lines or "health" in representative_lines:
            # A confidential request is visible to a company representative
            # only while that exact user owns its active workflow stage.
            allowed |= Q(pk__in=confidential_assigned_scope.filter(
                company_id__in=company_ids,
                kind__in=health_request_kinds,
            ).values("pk"))

    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST) or has_role(
        user, RoleAssignment.Role.INSURER_REP
    ):
        # WorkflowCase.current_assignee is the sole current-owner authority.
        # Prior assignees retain read access to the audit trail, but never gain
        # an action right from this visibility rule. The legacy assigned_to
        # field is consulted only for records that predate workflow creation.
        workflow_cases = WorkflowCase.objects.filter(
            content_type=content_type,
        ).annotate(domain_pk=Cast("object_id", BigIntegerField()))
        current_object_ids = workflow_cases.filter(
            current_assignee_id=user.pk,
            status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        ).values("domain_pk")
        historical_object_ids = WorkflowEvent.objects.filter(
            workflow_case__content_type=content_type,
        ).filter(
            Q(from_assignee_id=user.pk) | Q(to_assignee_id=user.pk)
        ).annotate(
            domain_pk=Cast("workflow_case__object_id", BigIntegerField())
        ).values("domain_pk")
        legacy_ids = qs.filter(assigned_to_id=user.pk).exclude(
            pk__in=workflow_cases.values("domain_pk")
        ).values("pk")
        assigned_scope = ServiceRequest.objects.filter(
            Q(pk__in=current_object_ids)
            | Q(pk__in=historical_object_ids)
            | Q(pk__in=legacy_ids),
            is_confidential=False,
        )
        role_scoped_ids = Q(pk__in=[])

        if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
            specialist_lines = line_codes_for(
                user, role=RoleAssignment.Role.INSURANCE_SPECIALIST
            )
            if specialist_lines:
                # Explicit assignment is the work grant for a request whose
                # kind has no intrinsic insurance-line mapping.
                role_scoped_ids |= Q(pk__in=assigned_scope.values("pk"))
                if "*" in specialist_lines or "health" in specialist_lines:
                    role_scoped_ids |= Q(pk__in=confidential_assigned_scope.filter(
                        kind__in=health_request_kinds,
                    ).values("pk"))

        insurer_ids = insurer_ids_for(user)
        if insurer_ids:
            from insurance.models import Contract, InsuranceLine
            from django.utils import timezone as django_timezone

            today = django_timezone.localdate()
            insured_company_ids = Contract.objects.filter(
                insurer_id__in=insurer_ids,
                line=InsuranceLine.HEALTH,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today,
            ).values("companies__pk")
            role_scoped_ids |= Q(pk__in=assigned_scope.filter(
                kind__in=health_request_kinds,
                company_id__in=insured_company_ids,
            ).values("pk"))
            role_scoped_ids |= Q(pk__in=confidential_assigned_scope.filter(
                kind__in=health_request_kinds,
                company_id__in=insured_company_ids,
            ).values("pk"))

        allowed |= role_scoped_ids

    if has_role(user, RoleAssignment.Role.INSURED_PERSON):
        # Employees must still see their own requests when a company
        # representative submitted the form on their behalf. Confidential
        # Medical requests remain limited to the linked insured person and
        # explicitly assigned workflow recipients; only minimum metadata is
        # available to non-global operational recipients.
        allowed |= (
            Q(submitted_by_id=user.pk)
            | Q(person__user_id=user.pk)
            | Q(person__employee__user_id=user.pk)
        )

    return qs.filter(allowed).distinct()


def can_view_claim(user, claim):
    return scoped_claims_for(user).filter(pk=claim.pk).exists()


def can_view_request(user, item):
    return scoped_requests_for(user).filter(pk=item.pk).exists()


def can_process_request(user, item):
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not item.pk
    ):
        return False

    # A configured workflow owns every action once it exists. The legacy
    # request form must never remain an alternate action path.
    from django.contrib.contenttypes.models import ContentType
    from workflow.models import WorkflowCase
    content_type = ContentType.objects.get_for_model(item, for_concrete_model=False)
    if WorkflowCase.objects.filter(
        content_type=content_type, object_id=str(item.pk)
    ).exists():
        return False

    if has_global_access(user):
        return True
    if item.is_confidential:
        return False
    from workflow.services import _scope_for_object
    scope = _scope_for_object(item)
    specialist_allowed = (
        has_role(
            user, RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=scope["line_code"],
        )
        if scope.get("line_code")
        # For an unclassified legacy request, explicit assignment_to is the
        # grant; an unrelated all-lines role is not required.
        else has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)
    )
    insurer_allowed = bool(scope.get("insurer_id")) and has_role(
        user,
        RoleAssignment.Role.INSURER_REP,
        insurer_id=scope["insurer_id"],
    )
    return (
        specialist_allowed or insurer_allowed
    ) and item.assigned_to_id == user.pk


def can_transition_request(user, item, target_status):
    """Legacy status mutation is disabled; all request decisions use WorkflowCase."""
    return False


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
    # This helper has no approved-workflow context, so it must never authorize a
    # direct write. The approved person-change workflow must perform the update
    # through its dedicated domain service after the final approval transition.
    return False


def require_object_access(allowed, message="شما مجوز دسترسی به این رکورد را ندارید."):
    if not allowed:
        raise PermissionDenied(message)
