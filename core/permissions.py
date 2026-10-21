from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

PRIVILEGED = {"system_admin", "department_head"}
INSURANCE_STAFF = PRIVILEGED | {"insurance_specialist"}
CLAIM_WIDE_ROLES = PRIVILEGED | {"insurance_specialist", "auditor"}


def role_required(*roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_superuser and request.user.role not in roles:
                raise PermissionDenied("شما مجوز دسترسی به این بخش را ندارید.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def scoped_claims_for(user):
    """Apply tenant and insurer scoping at the queryset boundary."""
    from claims.models import Claim

    qs = Claim.objects.select_related("person", "person__company", "contract", "insurer")
    if user.is_superuser or user.role in CLAIM_WIDE_ROLES:
        return qs
    if user.role == "insurer":
        return qs.filter(insurer_id=user.insurer_id) if user.insurer_id else qs.none()
    if user.role == "subsidiary_rep":
        return qs.filter(person__company_id=user.company_id) if user.company_id else qs.none()
    if user.role == "employee":
        if not user.national_id:
            return qs.none()
        from django.db.models import Q
        return qs.filter(
            Q(person__national_id=user.national_id) |
            Q(person__employee__national_id=user.national_id)
        ).distinct()
    return qs.none()


def scoped_requests_for(user):
    from django.db.models import Q
    from requests_portal.models import ServiceRequest

    qs = ServiceRequest.objects.select_related("submitted_by", "company", "person", "assigned_to")
    if user.is_superuser or user.role in PRIVILEGED:
        return qs
    if user.role == "insurance_specialist":
        return qs.filter(
            Q(assigned_to=user) | Q(assigned_to__isnull=True, is_confidential=False)
        ).distinct()
    if user.role == "subsidiary_rep":
        return qs.filter(company_id=user.company_id, is_confidential=False) if user.company_id else qs.none()
    if user.role == "auditor":
        return qs.filter(is_confidential=False)
    return qs.filter(submitted_by=user)
