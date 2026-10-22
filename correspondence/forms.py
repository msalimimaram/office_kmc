from django import forms
from django.contrib.auth import get_user_model
from insurance.models import Contract, Insurer
from organizations.models import Company
from .models import Correspondence
from core.uploads import validate_uploaded_file


User = get_user_model()
INTERNAL_ASSIGNEE_ROLES = {"system_admin", "department_head", "insurance_specialist"}


class CorrespondenceForm(forms.ModelForm):
    class Meta:
        model = Correspondence
        fields = [
            "subject", "channel", "direction", "company", "insurer", "contract",
            "external_reference", "summary", "occurred_at", "follow_up_due",
            "follow_up_status", "assigned_to", "is_confidential", "attachment",
        ]
        widgets = {
            "occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "follow_up_due": forms.DateInput(attrs={"type": "date"}),
            "summary": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["company"].queryset = Company.objects.filter(is_active=True)
        self.fields["insurer"].queryset = Insurer.objects.filter(is_active=True)
        self.fields["contract"].queryset = Contract.objects.filter(is_active=True).select_related("insurer")
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True, role__in=INTERNAL_ASSIGNEE_ROLES
        ).order_by("last_name", "first_name", "username")
        if user.role == "insurance_specialist":
            self.fields.pop("is_confidential")
        if user.role == "subsidiary_rep" and user.company_id:
            self.fields.pop("company")
            self.fields.pop("assigned_to")
            self.fields.pop("is_confidential")
            self.fields["contract"].queryset = self.fields["contract"].queryset.filter(companies=user.company)
        elif user.role == "insurer" and user.insurer_id:
            self.fields.pop("assigned_to")
            self.fields.pop("is_confidential")
            self.fields["insurer"].queryset = Insurer.objects.filter(pk=user.insurer_id)
            self.fields["insurer"].initial = user.insurer_id
            self.fields["insurer"].disabled = True
            self.fields["contract"].queryset = self.fields["contract"].queryset.filter(insurer_id=user.insurer_id)
            self.fields["company"].queryset = self.fields["company"].filter(insurance_contracts__insurer_id=user.insurer_id).distinct()
        upload = self.fields["attachment"]
        upload.required = False

    def clean(self):
        cleaned = super().clean()
        company, contract, insurer = cleaned.get("company") or self.user.company, cleaned.get("contract"), cleaned.get("insurer")
        if contract and insurer and contract.insurer_id != insurer.pk:
            self.add_error("insurer", "بیمه‌گر با بیمه‌گر قرارداد مطابقت ندارد.")
        if contract and company and not contract.companies.filter(pk=company.pk).exists():
            self.add_error("contract", "قرارداد انتخاب‌شده برای شرکت مشخص‌شده نیست.")
        attachment = cleaned.get("attachment")
        if attachment:
            error = validate_uploaded_file(attachment, max_size=15 * 1024 * 1024)
            if error:
                self.add_error("attachment", error)
        return cleaned
