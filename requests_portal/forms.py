from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from accounts.access import company_ids_for, has_role
from accounts.models import RoleAssignment
from organizations.models import Person, PersonEmployment
from organizations.forms import current_company_id_for_person
from .models import ServiceRequest

LEGACY_PERSON_CHANGE_KINDS = {
    ServiceRequest.Kind.IDENTITY_CHANGE,
    ServiceRequest.Kind.IBAN_CHANGE,
}


class ServiceRequestForm(forms.ModelForm):
    person = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        required=False,
        label="بیمه‌شده مرتبط",
        help_text="در صورت مرتبط بودن درخواست با شخص، خود بیمه‌شده یا فرد تحت تکفل را انتخاب کنید.",
    )

    class Meta:
        model = ServiceRequest
        fields = ["kind", "person", "title", "description", "attachment"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, active_company_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.active_company_id = active_company_id
        self.fields["kind"].choices = [
            choice for choice in self.fields["kind"].choices
            if choice[0] not in LEGACY_PERSON_CHANGE_KINDS
        ]
        if not user:
            return

        if has_role(user, RoleAssignment.Role.INSURED_PERSON):
            person = getattr(user, "person_record", None)
            if person:
                self.fields["person"].queryset = Person.objects.filter(
                    Q(pk=person.pk) | Q(employee_id=person.pk),
                ).order_by("relationship", "last_name", "first_name")
            elif user.national_id:
                self.fields["person"].queryset = Person.objects.filter(
                    Q(national_id=user.national_id) | Q(employee__national_id=user.national_id)
                ).distinct().order_by("relationship", "last_name", "first_name")
        elif has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            if self.active_company_id not in company_ids:
                self.active_company_id = (
                    next(iter(company_ids)) if len(company_ids) == 1 else None
                )
            if self.active_company_id:
                today = timezone.localdate()
                active_employee_ids = PersonEmployment.objects.filter(
                    company_id=self.active_company_id,
                    status=PersonEmployment.Status.ACTIVE,
                ).filter(
                    Q(valid_from__isnull=True) | Q(valid_from__lte=today)
                ).filter(
                    Q(valid_until__isnull=True) | Q(valid_until__gte=today)
                ).values_list("person_id", flat=True)
                any_employment_ids = PersonEmployment.objects.values_list(
                    "person_id", flat=True
                )
                legacy_person_ids = Person.objects.filter(
                    company_id=self.active_company_id
                ).exclude(
                    pk__in=any_employment_ids
                ).exclude(
                    employee_id__in=any_employment_ids
                ).values_list("pk", flat=True)
                self.fields["person"].queryset = Person.objects.filter(
                    Q(pk__in=active_employee_ids)
                    | Q(employee_id__in=active_employee_ids)
                    | Q(pk__in=legacy_person_ids)
                ).distinct().order_by("last_name", "first_name")
            else:
                self.fields["person"].queryset = Person.objects.none()
        elif not has_role(user, RoleAssignment.Role.INSURED_PERSON):
            self.fields.pop("person")

    def clean(self):
        cleaned = super().clean()
        submitted_kind = self.data.get(self.add_prefix("kind"))
        if submitted_kind in LEGACY_PERSON_CHANGE_KINDS:
            self.add_error(
                "kind",
                "اصلاح اطلاعات هویتی و شبا فقط از مسیر مستقل «درخواست اصلاح اطلاعات شخص» ثبت می‌شود.",
            )
        person = cleaned.get("person")
        if person and self.user:
            if has_role(self.user, RoleAssignment.Role.INSURED_PERSON):
                own_person = getattr(self.user, "person_record", None)
                if own_person and person.pk != own_person.pk and person.employee_id != own_person.pk:
                    self.add_error("person", "فقط خود بیمه‌شده یا افراد تحت تکفل او مجاز هستند.")
            if has_role(self.user, RoleAssignment.Role.SUBSIDIARY_REP):
                company_ids = company_ids_for(
                    self.user, role=RoleAssignment.Role.SUBSIDIARY_REP
                )
                current_company_id = current_company_id_for_person(person)
                if (
                    self.active_company_id not in company_ids
                    or current_company_id != self.active_company_id
                ):
                    self.add_error(
                        "person",
                        "شخص انتخاب‌شده در اشتغال جاری شرکت فعال شما قرار ندارد.",
                    )
            elif (
                has_role(self.user, RoleAssignment.Role.INSURED_PERSON)
                and current_company_id_for_person(person) is None
            ):
                self.add_error(
                    "person",
                    "برای شخص انتخاب‌شده اشتغال جاری معتبر ثبت نشده است.",
                )
        if (
            self.user
            and has_role(self.user, RoleAssignment.Role.INSURED_PERSON)
            and cleaned.get("kind") == ServiceRequest.Kind.MEDICAL_ASSISTANCE
            and not person
        ):
            self.add_error("person", "برای درخواست کمک‌هزینه درمان، انتخاب بیمه‌شده یا فرد تحت تکفل الزامی است.")
        return cleaned

    def clean_attachment(self):
        upload = self.cleaned_data.get("attachment")
        if upload:
            from core.uploads import validate_uploaded_file
            error = validate_uploaded_file(upload, max_size=10 * 1024 * 1024)
            if error:
                raise ValidationError(error)
        return upload
