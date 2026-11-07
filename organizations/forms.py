from django import forms
from .models import Company, CompanyLeadershipTitle, Person, PersonEmployment
from accounts.access import company_ids_for, has_global_access
from accounts.models import RoleAssignment
from django.db.models import Q
from django.utils import timezone

class PersonChangeRequestForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["personnel_code", "national_id", "first_name", "last_name", "mobile", "iban", "is_insured"]
        widgets = {"national_id": forms.TextInput(attrs={"inputmode": "numeric"})}


class CompanyLeadershipTitleForm(forms.ModelForm):
    class Meta:
        model = CompanyLeadershipTitle
        fields = ["company", "person", "title", "valid_from", "valid_until"]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if has_global_access(user):
            company_ids = set(Company.objects.filter(is_active=True).values_list("pk", flat=True))
        else:
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        today = timezone.localdate()
        employed_ids = PersonEmployment.objects.filter(company_id__in=company_ids).filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=today)
        ).values_list("person_id", flat=True)
        self.fields["company"].queryset = Company.objects.filter(pk__in=company_ids, is_active=True)
        self.fields["person"].queryset = Person.objects.filter(
            Q(company_id__in=company_ids) | Q(pk__in=employed_ids),
            is_active=True,
        ).distinct()
