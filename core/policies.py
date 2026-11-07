from django.core.exceptions import PermissionDenied

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from .permissions import scoped_claims_for, scoped_requests_for


CLAIM_EDIT_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DEPARTMENT_HEAD,
    RoleAssignment.Role.INSURANCE_SPECIALIST,
}
CLAIM_DECISION_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DEPARTMENT_HEAD,
    RoleAssignment.Role.INSURANCE_SPECIALIST,
}
REQUEST_DECISION_ROLES = {
    RoleAssignment.Role.SYSTEM_ADMIN,
    RoleAssignment.Role.DEPARTMENT_HEAD,
}

# Transitional state map for the legacy request page. The new Workflow app
# will replace this hard-coded table with versioned definitions.
REQUEST_TRANSITIONS = {
    "submitted": {"in_review", "needs_info", "referred", "rejected"},
    "in_review": {"needs_info", "referred", "approved", "rejected", "completed"},
    "needs_info": {"in_review", "referred", "rejected"},
    "referred": {"in_review", "needs_info", "approved", "rejected"},
    "approved": {"completed", "closed"},
    "rejected": {"closed"},
    "completed": {"closed"},
    "closed": set(),
}


def can_view_claim(user, claim):
    return scoped_claims_for(user).filter(pk=claim.pk).exists()


def can_view_request(user, item):
    return scoped_requests_for(user).filter(pk=item.pk).exists()


def can_process_request(user, item):
    if has_global_access(user):
        return True
    if item.is_confidential:
        return False
    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        return item.assigned_to_id == user.pk
    if has_role(user, RoleAssignment.Role.INSURER_REP):
        return item.assigned_to_id == user.pk
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        return item.company_id in set(
            scoped_requests_for(user).values_list("company_id", flat=True).distinct()
        )
    return False


def can_transition_request(user, item, target_status):
    if not can_process_request(user, item):
        return False
    if target_status == item.status:
        return True
    if target_status not in REQUEST_TRANSITIONS.get(item.status, set()):
        return False
    if has_role(user, RoleAssignment.Role.INSURER_REP):
        # Insurer staff may return responses but cannot approve or finally close.
        return target_status not in {"approved", "rejected", "completed", "closed"}
    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        return target_status not in {"approved", "rejected", "completed", "closed"}
    return True


def can_edit_claim(user, claim):
    return can_view_claim(user, claim) and any(
        has_role(user, role)
        for role in CLAIM_EDIT_ROLES
    )


def can_decide_claim(user, claim):
    return can_view_claim(user, claim) and any(
        has_role(user, role)
        for role in CLAIM_DECISION_ROLES
    )


def can_edit_iban(user, person):
    # Direct modification is restricted. Normal employee/representative flows
    # must create an approved change request instead.
    return has_global_access(user)


def require_object_access(allowed, message="شما مجوز دسترسی به این رکورد را ندارید."):
    if not allowed:
        raise PermissionDenied(message)
