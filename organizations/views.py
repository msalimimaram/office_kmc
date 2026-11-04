from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.access import company_ids_for, has_global_access, has_role
from accounts.models import RoleAssignment
from organizations.models import Person, PersonEmployment


@login_required
def people_list(request):
    user = request.user
    if has_global_access(user):
        people = Person.objects.select_related("company", "employee", "user")
    elif has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
        company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        employment_people = PersonEmployment.objects.filter(
            company_id__in=company_ids
        ).values_list("person_id", flat=True)
        people = Person.objects.filter(
            Q(company_id__in=company_ids) | Q(pk__in=employment_people)
        ).select_related("company", "employee", "user")
    elif has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        # Specialists can see the insured register as needed for their line work.
        people = Person.objects.select_related("company", "employee", "user")
    elif has_role(user, RoleAssignment.Role.INSURED_PERSON):
        people = Person.objects.filter(
            Q(user_id=user.pk) | Q(employee__user_id=user.pk)
        ).select_related("company", "employee", "user")
        if not people.exists() and user.national_id:
            people = Person.objects.filter(
                Q(national_id=user.national_id) | Q(employee__national_id=user.national_id)
            ).select_related("company", "employee", "user")
    else:
        raise PermissionDenied

    query = request.GET.get("q", "").strip()[:100]
    if query and (has_global_access(user) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP, RoleAssignment.Role.INSURANCE_SPECIALIST)):
        people = people.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(personnel_code__icontains=query)
            | Q(national_id__icontains=query)
        )
    page_obj = Paginator(
        people.distinct().order_by("last_name", "first_name", "pk"), 25
    ).get_page(request.GET.get("page"))
    return render(request, "organizations/people_list.html", {
        "people": page_obj.object_list,
        "page_obj": page_obj,
        "search_query": query,
    })
