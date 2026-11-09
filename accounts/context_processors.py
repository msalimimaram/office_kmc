from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access, has_role, is_insurance_staff
from accounts.models import PositionAssignment, RoleAssignment, UserNotification


def access_flags(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"access": {}, "unread_notification_count": 0}
    staff = is_insurance_staff(user)
    today = timezone.localdate()
    active_position_assignment = PositionAssignment.objects.filter(
        user=user,
        is_active=True,
        valid_from__lte=today,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    assigned_correspondence = active_position_assignment.filter(
        position__level__in=[
            PositionAssignment.position.field.related_model.Level.SUPERVISOR,
            PositionAssignment.position.field.related_model.Level.RESPONSIBLE,
        ],
    ).exists()
    notification_access = (
        staff
        or has_role(user, RoleAssignment.Role.INSURED_PERSON)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
        or active_position_assignment.exists()
    )
    delegation_inbox_access = has_global_access(user)
    if not delegation_inbox_access:
        # A recipient sees the inbox link only when a delegation was issued
        # to this account. Historical rules keep the read-only empty inbox
        # available after revocation for a bookmarked URL.
        from delegations.models import WorkDelegation
        delegation_inbox_access = WorkDelegation.objects.filter(
            delegate_to=user
        ).exists()
    return {
        "unread_notification_count": UserNotification.objects.filter(
            recipient=user, read_at__isnull=True
        ).count() if notification_access else 0,
        "access": {
            "notifications": notification_access,
            "delegation_inbox": delegation_inbox_access,
            "delegation_manage": has_global_access(user),
            "staff": staff,
            "global": has_global_access(user),
            "system_admin": has_role(user, RoleAssignment.Role.SYSTEM_ADMIN),
            "insured": has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "company_rep": has_role(user, RoleAssignment.Role.SUBSIDIARY_REP),
            "insurer_rep": has_role(user, RoleAssignment.Role.INSURER_REP),
            "claims": staff or has_role(user, RoleAssignment.Role.INSURED_PERSON) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "contracts": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "assets": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "correspondence": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP) or assigned_correspondence,
            "requests": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "people": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "leadership_titles": has_global_access(user) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP),
            "tasks": staff or PositionAssignment.objects.filter(user=user, is_active=True, valid_from__lte=timezone.localdate()).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate())).exists(),
            "imports": staff or has_role(user, RoleAssignment.Role.INSURER_REP),
        },
    }
