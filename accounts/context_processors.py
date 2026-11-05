from accounts.access import active_assignments, has_global_access, has_role, is_insurance_staff
from accounts.models import RoleAssignment


def access_flags(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"access": {}}
    staff = is_insurance_staff(user)
    return {
        "access": {
            "staff": staff,
            "global": has_global_access(user),
            "insured": has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "company_rep": has_role(user, RoleAssignment.Role.SUBSIDIARY_REP),
            "insurer_rep": has_role(user, RoleAssignment.Role.INSURER_REP),
            "claims": staff or has_role(user, RoleAssignment.Role.INSURED_PERSON) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "contracts": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "assets": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "correspondence": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURER_REP),
            "requests": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "people": staff or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP) or has_role(user, RoleAssignment.Role.INSURED_PERSON),
            "tasks": staff or active_assignments(user).exists(),
            "imports": staff or has_role(user, RoleAssignment.Role.INSURER_REP),
        },
    }
