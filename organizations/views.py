from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from .models import Person

@login_required
def people_list(request):
    if request.user.role in {"system_admin", "department_head", "insurance_specialist", "auditor"} or request.user.is_superuser:
        people = Person.objects.select_related("company", "employee")
    elif request.user.role == "subsidiary_rep":
        people = Person.objects.filter(company=request.user.company)
    elif request.user.role == "employee":
        people = Person.objects.filter(national_id=request.user.national_id) | Person.objects.filter(employee__national_id=request.user.national_id)
    else:
        raise PermissionDenied
    return render(request, "organizations/people_list.html", {"people": people.distinct()})
