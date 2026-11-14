from django import forms
from .models import Company, CompanyLeadershipPosition, CompanyLeadershipTitle, Person, PersonEmployment, PersonChangeRequest, normalize_national_id
from insurance.models import Contract
from accounts.access import company_ids_for, has_global_access
from accounts.models import RoleAssignment
from django.db.models import Q
from django.utils import timezone

def current_company_id_for_person(person):
    employee = person.employee if person.employee_id else person
    today = timezone.localdate()
    active = PersonEmployment.objects.filter(
        person_id=employee.pk,
        status=PersonEmployment.Status.ACTIVE,
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=today)
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).order_by("-valid_from", "-pk").first()
    if active:
        return active.company_id
    if not PersonEmployment.objects.filter(person_id=employee.pk).exists():
        return employee.company_id or person.company_id
    return None


class PersonChangeRequestForm(forms.Form):
    person = forms.ModelChoiceField(
        label="شخص مورد درخواست",
        queryset=Person.objects.none(),
    )
    contract = forms.ModelChoiceField(
        label="قرارداد / بیمه‌گر مرتبط",
        queryset=Contract.objects.none(),
    )
    change_type = forms.ChoiceField(
        label="اطلاعات قابل اصلاح",
        choices=PersonChangeRequest.ChangeType.choices,
    )
    requested_value = forms.CharField(
        label="مقدار صحیح درخواستی",
        max_length=160,
    )
    reason = forms.CharField(
        label="دلیل درخواست",
        min_length=10,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        people = Person.objects.filter(
            Q(user_id=user.pk) | Q(employee__user_id=user.pk),
            is_active=True,
            is_insured=True,
        ).select_related("employee", "user").distinct()
        if not people.exists() and getattr(user, "national_id", ""):
            legacy = Person.objects.filter(
                national_id=normalize_national_id(user.national_id),
                is_active=True,
                is_insured=True,
            ).first()
            if legacy:
                people = Person.objects.filter(
                    Q(pk=legacy.pk) | Q(employee_id=legacy.pk),
                    is_active=True,
                    is_insured=True,
                ).select_related("employee", "user")
        self.fields["person"].queryset = people

        company_ids = {
            company_id
            for person in people
            if (company_id := current_company_id_for_person(person))
        }
        today = timezone.localdate()
        self.fields["contract"].queryset = Contract.objects.filter(
            companies__pk__in=company_ids,
            status=Contract.Status.ACTIVE,
            is_active=True,
            start_date__lte=today,
            end_date__gte=today,
        ).select_related("insurer").distinct().order_by("code")

    def clean(self):
        cleaned = super().clean()
        person = cleaned.get("person")
        contract = cleaned.get("contract")
        if person and contract:
            company_id = current_company_id_for_person(person)
            if not company_id:
                self.add_error("person", "برای این شخص شرکت محل اشتغال فعال و معتبر پیدا نشد.")
            elif not contract.companies.filter(pk=company_id).exists():
                self.add_error("contract", "قرارداد انتخاب‌شده متعلق به شرکت محل اشتغال این شخص نیست.")
        return cleaned


class CompanyLeadershipTitleForm(forms.ModelForm):
    class Meta:
        model = CompanyLeadershipTitle
        fields = ["company", "person", "position", "title", "valid_from", "valid_until"]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        # The title is a snapshot derived from the selected company position.
        # Keep it in the ModelForm so model validation errors map to a field
        # instead of raising ValueError for an unknown "title" field.
        self.fields["title"].required = False
        self.fields["title"].disabled = True
        if has_global_access(user):
            company_ids = set(Company.objects.filter(is_active=True).values_list("pk", flat=True))
        else:
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        today = timezone.localdate()
        employment_history_ids = PersonEmployment.objects.values_list(
            "person_id", flat=True
        )
        active_employment_ids = PersonEmployment.objects.filter(
            company_id__in=company_ids,
            status=PersonEmployment.Status.ACTIVE,
        ).filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=today)
        ).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=today)
        ).values_list("person_id", flat=True)
        # The legacy Person.company pointer is a fallback only when the
        # primary employee has no employment history. A stale pointer must
        # not expose a person in a former company's title-entry form.
        legacy_people = Person.objects.filter(
            company_id__in=company_ids,
            is_active=True,
        ).filter(
            Q(employee__isnull=True) | Q(employee__is_active=True)
        ).exclude(
            pk__in=employment_history_ids
        ).exclude(
            employee_id__in=employment_history_ids
        )
        self.fields["company"].queryset = Company.objects.filter(pk__in=company_ids, is_active=True)
        self.fields["person"].queryset = Person.objects.filter(
            Q(
                pk__in=active_employment_ids,
                relationship=Person.Relationship.EMPLOYEE,
                employee__isnull=True,
            )
            | Q(
                employee_id__in=active_employment_ids,
                employee__is_active=True,
            )
            | Q(pk__in=legacy_people.values("pk")),
            is_active=True,
        ).distinct()
        self.fields["position"].queryset = CompanyLeadershipPosition.objects.filter(
            company_id__in=company_ids, is_active=True,
        ).select_related("company").order_by("company__name", "title")

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        position = cleaned.get("position")
        if company and position and position.company_id != company.pk:
            self.add_error("position", "عنوان انتخاب‌شده متعلق به شرکت دیگری است.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.title = self.cleaned_data["position"].title
        if commit:
            obj.save()
        return obj
