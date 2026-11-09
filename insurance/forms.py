from django import forms

from accounts.access import has_global_access, has_role, line_codes_for
from accounts.models import RoleAssignment
from core.uploads import validate_uploaded_file
from organizations.models import Company

from .models import Contract, Insurer, InsuranceLine


class ContractForm(forms.ModelForm):
    revision_description = forms.CharField(
        label="شرح نسخه/تغییر",
        min_length=5,
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    effective_date = forms.DateField(
        label="تاریخ اثر نسخه",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    revision_document = forms.FileField(
        label="سند قرارداد/الحاقیه",
        required=False,
    )

    class Meta:
        model = Contract
        fields = [
            "code",
            "title",
            "insurer",
            "line",
            "companies",
            "start_date",
            "end_date",
            "coverage_summary",
            "terms",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "coverage_summary": forms.Textarea(attrs={"rows": 3}),
            "terms": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        insurer_qs = Insurer.objects.filter(is_active=True)
        company_qs = Company.objects.filter(is_active=True)
        if self.instance.pk:
            insurer_qs = (insurer_qs | Insurer.objects.filter(pk=self.instance.insurer_id)).distinct()
            existing_company_ids = self.instance.companies.values_list("pk", flat=True)
            company_qs = (company_qs | Company.objects.filter(pk__in=existing_company_ids)).distinct()
        self.fields["insurer"].queryset = insurer_qs.order_by("name")
        self.fields["companies"].queryset = company_qs.order_by("name")

        if not has_global_access(user):
            if not has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
                self.fields["line"].choices = []
                self.fields["insurer"].queryset = Insurer.objects.none()
                self.fields["companies"].queryset = Company.objects.none()
            else:
                allowed_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
                if "*" not in allowed_lines:
                    self.fields["line"].choices = [
                        (key, label) for key, label in InsuranceLine.choices
                        if key in allowed_lines
                    ]

    def clean(self):
        cleaned = super().clean()
        line = cleaned.get("line")
        if (
            line
            and not has_global_access(self.user)
            and not has_role(
                self.user,
                RoleAssignment.Role.INSURANCE_SPECIALIST,
                line_code=line,
            )
        ):
            self.add_error("line", "ثبت قرارداد در این رشته در محدوده انتصاب شما نیست.")

        effective_date = cleaned.get("effective_date")
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if effective_date and start_date and effective_date < start_date:
            self.add_error("effective_date", "تاریخ اثر نسخه نمی‌تواند قبل از شروع قرارداد باشد.")
        if effective_date and end_date and effective_date > end_date:
            self.add_error("effective_date", "تاریخ اثر نسخه نمی‌تواند بعد از پایان قرارداد باشد.")

        upload = cleaned.get("revision_document")
        if upload:
            error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
            if error:
                self.add_error("revision_document", error)
        return cleaned

class ContractTerminationForm(forms.Form):
    effective_date = forms.DateField(
        label="تاریخ اثر فسخ",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    notice_date = forms.DateField(
        label="تاریخ اعلام به بیمه‌گر",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reason = forms.CharField(
        label="علت و مستندات فسخ",
        min_length=10,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    document = forms.FileField(label="سند درخواست فسخ", required=False)

    def __init__(self, *args, contract, **kwargs):
        super().__init__(*args, **kwargs)
        self.contract = contract

    def clean(self):
        cleaned = super().clean()
        effective_date = cleaned.get("effective_date")
        notice_date = cleaned.get("notice_date")
        if effective_date and effective_date < self.contract.start_date:
            self.add_error("effective_date", "تاریخ اثر فسخ نمی‌تواند قبل از شروع قرارداد باشد.")
        if effective_date and effective_date > self.contract.end_date:
            self.add_error("effective_date", "تاریخ اثر فسخ نمی‌تواند بعد از پایان قرارداد باشد.")
        if notice_date and effective_date and notice_date > effective_date:
            self.add_error("notice_date", "تاریخ اعلام نمی‌تواند بعد از تاریخ اثرگذاری باشد.")
        upload = cleaned.get("document")
        if upload:
            error = validate_uploaded_file(upload, max_size=20 * 1024 * 1024)
            if error:
                self.add_error("document", error)
        return cleaned
