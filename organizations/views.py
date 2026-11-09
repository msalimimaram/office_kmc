from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.access import company_ids_for, has_global_access, has_role, line_codes_for
from accounts.models import RoleAssignment
from core.permissions import scoped_claims_for, scoped_requests_for
from auditlog.services import record_event
from workflow.models import WorkflowCase, WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow
from organizations.models import Company, CompanyLeadershipTitle, Person, PersonEmployment, PersonChangeRequest
from .forms import CompanyLeadershipTitleForm, PersonChangeRequestForm, current_company_id_for_person


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



def _person_change_scope(user):
    queryset = PersonChangeRequest.objects.select_related(
        "person", "company", "contract", "contract__insurer",
        "requested_by", "approved_by", "rejected_by",
    )
    if has_global_access(user):
        return queryset

    allowed = Q(requested_by_id=user.pk)
    company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    if company_ids:
        representative_lines = line_codes_for(
            user, role=RoleAssignment.Role.SUBSIDIARY_REP
        )
        if "*" in representative_lines:
            allowed |= Q(company_id__in=company_ids)
        elif representative_lines:
            allowed |= Q(
                company_id__in=company_ids,
                contract__line__in=representative_lines,
            )

    content_type = ContentType.objects.get_for_model(
        PersonChangeRequest, for_concrete_model=False
    )
    assigned_object_ids = WorkflowCase.objects.filter(
        content_type=content_type,
        current_assignee_id=user.pk,
        status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
    ).values_list("object_id", flat=True)
    assigned_ids = [
        int(value) for value in assigned_object_ids
        if str(value).isdigit()
    ]
    if assigned_ids:
        allowed |= Q(pk__in=assigned_ids)

    can_access = any(
        has_role(user, role)
        for role in (
            RoleAssignment.Role.INSURED_PERSON,
            RoleAssignment.Role.SUBSIDIARY_REP,
            RoleAssignment.Role.INSURER_REP,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
        )
    )
    if not can_access:
        raise PermissionDenied
    return queryset.filter(allowed).distinct()


@login_required
def person_change_list(request):
    changes = _person_change_scope(request.user)
    page_obj = Paginator(
        changes.order_by("-created_at", "-pk"),
        25,
    ).get_page(request.GET.get("page"))
    return render(request, "organizations/person_change_list.html", {
        "changes": page_obj.object_list,
        "page_obj": page_obj,
        "can_create": has_role(request.user, RoleAssignment.Role.INSURED_PERSON),
    })


@login_required
def person_change_create(request):
    if not has_role(request.user, RoleAssignment.Role.INSURED_PERSON):
        raise PermissionDenied("ثبت درخواست اصلاح اطلاعات فقط برای بیمه‌شده اصلی مجاز است.")
    form = PersonChangeRequestForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                person = form.cleaned_data["person"]
                contract = form.cleaned_data["contract"]
                change_type = form.cleaned_data["change_type"]
                field_name = PersonChangeRequest.FIELD_MAP[change_type]
                company_id = current_company_id_for_person(person)
                if not company_id:
                    raise ValidationError("شرکت محل اشتغال فعال برای شخص انتخاب‌شده پیدا نشد.")

                if change_type == PersonChangeRequest.ChangeType.PERSONNEL_CODE:
                    today = timezone.localdate()
                    employment = PersonEmployment.objects.filter(
                        person_id=person.pk,
                        company_id=company_id,
                        status=PersonEmployment.Status.ACTIVE,
                    ).filter(
                        Q(valid_from__isnull=True) | Q(valid_from__lte=today)
                    ).filter(
                        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
                    ).order_by("-valid_from", "-pk").first()
                    current = employment.personnel_code if employment else person.personnel_code
                else:
                    current = getattr(person, field_name)
                current_value = current.isoformat() if hasattr(current, "isoformat") else str(current or "")

                item = PersonChangeRequest(
                    person=person,
                    company_id=company_id,
                    contract=contract,
                    requested_by=request.user,
                    change_type=change_type,
                    current_value=current_value,
                    requested_value=form.cleaned_data["requested_value"].strip(),
                    reason=form.cleaned_data["reason"].strip(),
                )
                item.save()

                definition = WorkflowDefinition.objects.filter(
                    code="person_change",
                    is_active=True,
                ).order_by("-version").first()
                if not definition:
                    raise ValidationError(
                        "گردش‌کار فعال person_change برای بررسی اصلاح اطلاعات پیکربندی نشده است."
                    )
                assignee, delegation = resolve_initial_assignee(
                    definition=definition,
                    obj=item,
                    return_delegation=True,
                    company_id=company_id,
                    insurer_id=contract.insurer_id,
                    line_code=contract.line,
                    owner_user_id=request.user.pk,
                    exclude_user_id=(
                        None
                        if has_role(
                            request.user,
                            RoleAssignment.Role.SUBSIDIARY_REP,
                            company_id=company_id,
                        )
                        else request.user.pk
                    ),
                )
                case = start_workflow(
                    obj=item,
                    code="person_change",
                    actor=request.user,
                    assignee=assignee,
                    delegation=delegation,
                    note=item.reason,
                )

                requested_value = item.requested_value
                if item.change_type in {
                    PersonChangeRequest.ChangeType.MOBILE,
                    PersonChangeRequest.ChangeType.IBAN,
                    PersonChangeRequest.ChangeType.NATIONAL_ID,
                }:
                    requested_value = "*" * max(0, len(requested_value) - 4) + requested_value[-4:]
                record_event(
                    actor=request.user,
                    action="person_change_requested",
                    obj=item,
                    summary=f"درخواست اصلاح {item.get_change_type_display()} ثبت و برای بررسی ارجاع شد.",
                    after_data={
                        "person_id": person.pk,
                        "company_id": company_id,
                        "contract_id": contract.pk,
                        "workflow_case_id": case.pk,
                        "change_type": item.change_type,
                        "current_value": (
                            "*" * max(0, len(current_value) - 4) + current_value[-4:]
                            if item.change_type in {
                                PersonChangeRequest.ChangeType.MOBILE,
                                PersonChangeRequest.ChangeType.IBAN,
                                PersonChangeRequest.ChangeType.NATIONAL_ID,
                            }
                            else current_value
                        ),
                        "requested_value": requested_value,
                    },
                    request=request,
                )
        except (ValidationError, PermissionDenied) as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "درخواست اصلاح اطلاعات ثبت و برای بررسی نماینده شرکت ارجاع شد.")
            return redirect("person_change_detail", pk=item.pk)

    return render(request, "organizations/person_change_form.html", {
        "form": form,
    })


@login_required
def person_change_detail(request, pk):
    item = get_object_or_404(_person_change_scope(request.user), pk=pk)
    content_type = ContentType.objects.get_for_model(
        PersonChangeRequest, for_concrete_model=False
    )
    case = WorkflowCase.objects.filter(
        content_type=content_type,
        object_id=str(item.pk),
    ).select_related("current_step", "current_assignee").first()
    can_open_workflow = bool(
        case and (
            has_global_access(request.user)
            or case.current_assignee_id == request.user.pk
        )
    )
    can_view_full_values = bool(
        has_global_access(request.user)
        or item.requested_by_id == request.user.pk
        or (case and case.current_assignee_id == request.user.pk)
    )
    current_value_display = item.current_value
    requested_value_display = item.requested_value
    if not can_view_full_values:
        current_text = str(item.current_value or "")
        requested_text = str(item.requested_value or "")
        if item.change_type == PersonChangeRequest.ChangeType.IBAN:
            current_value_display = f"••••{current_text[-4:]}" if current_text else "—"
            requested_value_display = f"••••{requested_text[-4:]}" if requested_text else "—"
        elif item.change_type == PersonChangeRequest.ChangeType.MOBILE:
            current_value_display = f"{current_text[:3]}••••{current_text[-2:]}" if current_text else "—"
            requested_value_display = f"{requested_text[:3]}••••{requested_text[-2:]}" if requested_text else "—"
        elif item.change_type == PersonChangeRequest.ChangeType.NATIONAL_ID:
            current_value_display = f"••••••{current_text[-4:]}" if current_text else "—"
            requested_value_display = f"••••••{requested_text[-4:]}" if requested_text else "—"
        elif item.change_type == PersonChangeRequest.ChangeType.BIRTH_DATE:
            current_value_display = "••••/••/••" if current_text else "—"
            requested_value_display = "••••/••/••" if requested_text else "—"
    return render(request, "organizations/person_change_detail.html", {
        "item": item,
        "workflow_case": case,
        "can_open_workflow": can_open_workflow,
        "can_view_full_values": can_view_full_values,
        "current_value_display": current_value_display,
        "requested_value_display": requested_value_display,
    })
