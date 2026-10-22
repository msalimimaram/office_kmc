from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import Person


@login_required
def people_list(request):
    if request.user.role in {"system_admin", "department_head", "insurance_specialist", "auditor"} or request.user.is_superuser:
        people = Person.objects.select_related("company", "employee")
    elif request.user.role == "subsidiary_rep":
        if not request.user.company_id:
            people = Person.objects.none()
        else:
            people = Person.objects.filter(company_id=request.user.company_id)
    elif request.user.role == "employee":
        if not request.user.national_id:
            people = Person.objects.none()
        else:
            people = Person.objects.filter(
                Q(national_id=request.user.national_id) |
                Q(employee__national_id=request.user.national_id)
            )
    else:
        raise PermissionDenied
    people = people.select_related("company", "employee")
    query = request.GET.get("q", "").strip()[:100]
    if query:
        people = people.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(personnel_code__icontains=query) |
            Q(national_id__icontains=query)
        )
    page_obj = Paginator(people.distinct().order_by("last_name", "first_name", "pk"), 25).get_page(request.GET.get("page"))
    return render(request, "organizations/people_list.html", {
        "people": page_obj.object_list, "page_obj": page_obj, "search_query": query,
    })
