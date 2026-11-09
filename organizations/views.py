from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.access import company_ids_for, has_global_access, has_role
from accounts.models import RoleAssignment
from core.permissions import scoped_claims_for, scoped_requests_for
from auditlog.services import record_event
from organizations.models import Company, CompanyLeadershipTitle, Person, PersonEmployment
from .forms import CompanyLeadershipTitleForm


@login_required
def people_list(request):
    user = request.user

    if has_global_access(user):
        people = Person.objects.all()
    else:
        # A user may hold several simultaneous assignments. Build the union of
        # each valid scope instead of letting the first matching role shadow the
        # rest. Specialists must never receive the unrestricted people register.
        visible_people = Q(pk__in=[])
        has_people_scope = False

        if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            if company_ids:
                employment_people = PersonEmployment.objects.filter(
                    company_id__in=company_ids
                ).values_list("person_id", flat=True)
                visible_people |= (
                    Q(company_id__in=company_ids) | Q(pk__in=employment_people)
                )
                has_people_scope = True

        if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
            claims = scoped_claims_for(user)
            assigned_requests = scoped_requests_for(user).exclude(person__isnull=True)
            visible_people |= (
                Q(pk__in=claims.values("person_id"))
                | Q(pk__in=claims.exclude(primary_insured__isnull=True).values("primary_insured_id"))
                | Q(pk__in=assigned_requests.values("person_id"))
            )
            has_people_scope = True

        if has_role(user, RoleAssignment.Role.INSURED_PERSON):
            visible_people |= Q(user_id=user.pk) | Q(employee__user_id=user.pk)
            if user.national_id:
                visible_people |= Q(national_id=user.national_id) | Q(employee__national_id=user.national_id)
            has_people_scope = True

        if not has_people_scope:
            raise PermissionDenied
        people = Person.objects.filter(visible_people)

    people = people.select_related("company", "employee", "user").prefetch_related(
        "leadership_titles"
    )

    query = request.GET.get("q", "").strip()[:100]
    if query and (
        has_global_access(user)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP, RoleAssignment.Role.INSURANCE_SPECIALIST)
    ):
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


@login_required
def company_leadership_titles(request):
    user = request.user
    if not (has_global_access(user) or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)):
        raise PermissionDenied

    if has_global_access(user):
        company_ids = set(Company.objects.filter(is_active=True).values_list("pk", flat=True))
    else:
        company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)

    titles = CompanyLeadershipTitle.objects.select_related(
        "company", "person", "declared_by"
    ).filter(company_id__in=company_ids)

    company_filter = request.GET.get("company", "").strip()
    if company_filter:
        if not company_filter.isdigit() or int(company_filter) not in company_ids:
            raise PermissionDenied
        titles = titles.filter(company_id=int(company_filter))

    if request.method == "POST":
        form = CompanyLeadershipTitleForm(request.POST, user=user)
        if form.is_valid():
            with transaction.atomic():
                item = form.save(commit=False)
                item.declared_by = user
                item.save()
                record_event(
                    actor=user,
                    action="company_leadership_title_declared",
                    obj=item,
                    summary=f"سمت {item.title} برای {item.person} در {item.company} ثبت شد.",
                    after_data={
                        "company_id": item.company_id,
                        "person_id": item.person_id,
                        "title": item.title,
                        "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                        "valid_until": item.valid_until.isoformat() if item.valid_until else None,
                    },
                    request=request,
                )
            messages.success(request, "سمت مدیریتی با موفقیت ثبت شد.")
            return redirect("company_leadership_titles")
    else:
        form = CompanyLeadershipTitleForm(user=user)

    companies = Company.objects.filter(pk__in=company_ids, is_active=True).order_by("name")
    return render(request, "organizations/leadership_titles.html", {
        "titles": titles.order_by("-valid_from", "company__name", "person__last_name"),
        "companies": companies,
        "selected_company": company_filter,
        "form": form,
        "can_manage_all": has_global_access(user),
    })
