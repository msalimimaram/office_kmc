from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

PRIVILEGED = {"system_admin", "department_head"}
INSURANCE_STAFF = PRIVILEGED | {"insurance_specialist"}
CLAIM_WIDE_ROLES = PRIVILEGED | {"insurance_specialist", "insurer", "auditor"}

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
    from claims.models import Claim
    qs = Claim.objects.select_related("person", "person__company", "contract", "insurer")
    if user.is_superuser or user.role in CLAIM_WIDE_ROLES:
        if user.role == "insurer" and not user.is_superuser:
            return qs.filter(insurer=user.insurer) if user.insurer_id else qs.none()
        return qs
    if user.role == "subsidiary_rep":
        return qs.filter(person__company=user.company)
    if user.role == "employee":
        return qs.filter(person__national_id=user.national_id) | qs.filter(person__employee__national_id=user.national_id)
    return qs.none()

def scoped_requests_for(user):
    from requests_portal.models import ServiceRequest
    qs = ServiceRequest.objects.select_related("submitted_by", "company", "person", "assigned_to")
    if user.is_superuser or user.role in PRIVILEGED:
        return qs
    if user.role == "insurance_specialist":
        return qs.filter(assigned_to=user) | qs.filter(assigned_to__isnull=True, is_confidential=False)
    if user.role == "subsidiary_rep":
        return qs.filter(company=user.company, is_confidential=False)
    return qs.filter(submitted_by=user)
