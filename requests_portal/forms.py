from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from accounts.access import company_ids_for, has_role
from accounts.models import RoleAssignment
from organizations.models import Person, PersonEmployment
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
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
            person_ids = PersonEmployment.objects.filter(
                company_id__in=company_ids
            ).values_list("person_id", flat=True)
            self.fields["person"].queryset = Person.objects.filter(
                Q(company_id__in=company_ids) | Q(pk__in=person_ids)
            ).distinct().order_by("last_name", "first_name")
        else:
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
            elif has_role(self.user, RoleAssignment.Role.SUBSIDIARY_REP):
                company_ids = company_ids_for(self.user, role=RoleAssignment.Role.SUBSIDIARY_REP)
                valid = PersonEmployment.objects.filter(
                    person_id=person.pk, company_id__in=company_ids
                ).exists() or person.company_id in company_ids
                if not valid:
                    self.add_error("person", "شخص انتخاب‌شده در محدوده شرکت شما نیست.")
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
