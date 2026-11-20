from accounts.access import (
    active_internal_position_assignments,
    active_company_id_for_user,
    company_ids_for,
    has_global_access,
    has_role,
    is_insurance_staff,
    is_unit_manager,
)
from accounts.models import RoleAssignment, UserNotification


def access_flags(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"access": {}, "unread_notification_count": 0}
    staff = is_insurance_staff(user)
    active_position_assignment = active_internal_position_assignments(user)
    unit_manager = is_unit_manager(user)
    position_titles = list(
        active_position_assignment.filter(
            unit__company__isnull=True,
            line_code__gt="",
        ).values_list("position__title", flat=True).distinct()
    )
    notification_access = (
        staff
        or has_role(user, RoleAssignment.Role.INSURED_PERSON)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
        or active_position_assignment.exists()
    )
    # Insured people follow their own requests from the Requests area; the
    # operational workflow inbox is only for staff, managers and routed recipients.
    workflow_access = (
        staff
        or unit_manager
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
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
    company_context_options = []
    active_company_id = None
    if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        from organizations.models import Company

        company_ids = company_ids_for(
            user, role=RoleAssignment.Role.SUBSIDIARY_REP
        )
        if company_ids:
            company_context_options = list(
                Company.objects.filter(
                    pk__in=company_ids, is_active=True
                ).order_by("name", "pk")
            )
            active_company_id = active_company_id_for_user(
                user, session=request.session
            )

    return {
        "company_context_options": company_context_options,
        "active_company_id": active_company_id,
        "unread_notification_count": UserNotification.objects.filter(
            recipient=user, read_at__isnull=True
        ).count() if notification_access else 0,
        "access": {
            "notifications": notification_access,
            "delegation_inbox": delegation_inbox_access,
            "workflow": workflow_access,
            "delegation_manage": has_global_access(user),
            "staff": staff,
            "global": has_global_access(user),
            "system_admin": has_role(user, RoleAssignment.Role.SYSTEM_ADMIN),
            "insured": has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "company_rep": has_role(user, RoleAssignment.Role.SUBSIDIARY_REP),
            "insurer_rep": has_role(user, RoleAssignment.Role.INSURER_REP),
            "unit_manager": unit_manager,
            "position_titles": position_titles,
            "primary_position": position_titles[0] if position_titles else "",
            "claims": staff or has_role(user, RoleAssignment.Role.INSURED_PERSON) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "contracts": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "assets": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "correspondence": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP) or unit_manager,
            "requests": (
                staff
                or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
                or has_role(user, RoleAssignment.Role.INSURER_REP)
                or has_role(user, RoleAssignment.Role.INSURED_PERSON)
            ),
            "documents": (
                staff
                or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
                or has_role(user, RoleAssignment.Role.INSURER_REP)
                or has_role(user, RoleAssignment.Role.INSURED_PERSON)
            ),
            "people": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "leadership_titles": has_global_access(user) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP),
            "tasks": staff or unit_manager,
            "imports": staff or has_role(user, RoleAssignment.Role.INSURER_REP),
            "reports": staff or unit_manager,
        },
    }
