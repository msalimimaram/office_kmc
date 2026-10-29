from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .permissions import PRIVILEGED, scoped_claims_for, scoped_requests_for


CLAIM_EDIT_ROLES = {"system_admin", "department_head", "insurance_specialist", "finance"}
CLAIM_DECISION_ROLES = {"system_admin", "department_head", "insurance_specialist"}
REQUEST_DECISION_ROLES = {"system_admin", "department_head"}

REQUEST_TRANSITIONS = {
    "submitted": {"in_review", "needs_info", "referred", "rejected"},
    "in_review": {"needs_info", "referred", "approved", "rejected", "completed"},
    "needs_info": {"in_review", "rejected"},
    "referred": {"in_review", "approved", "rejected"},
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
    if user.is_superuser or user.role in PRIVILEGED:
        return not (item.is_confidential and user.role not in PRIVILEGED and not user.is_superuser)
    if user.role != "insurance_specialist" or item.is_confidential:
        return False
    return item.assigned_to_id in (None, user.pk)


def can_transition_request(user, item, target_status):
    if not can_process_request(user, item):
        return False
    if target_status == item.status:
        return True
    if target_status not in REQUEST_TRANSITIONS.get(item.status, set()):
        return False
    if user.role == "insurance_specialist" and target_status in {"approved", "rejected", "completed", "closed"}:
        return False
    return True


def can_edit_claim(user, claim):
    return user.is_superuser or (
        user.role in CLAIM_EDIT_ROLES and can_view_claim(user, claim)
    )


def can_decide_claim(user, claim):
    return user.is_superuser or (
        user.role in CLAIM_DECISION_ROLES and can_view_claim(user, claim)
    )


def can_edit_iban(user, person):
    # IBAN is a sensitive financial attribute. It must never be edited directly
    # by an employee or company representative; changes go through the request workflow.
    return user.is_superuser or user.role in {"system_admin", "department_head", "finance"}


def require_object_access(allowed, message="شما مجوز دسترسی به این رکورد را ندارید."):
    if not allowed:
        raise PermissionDenied(message)
