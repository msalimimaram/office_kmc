from django import forms
from django.contrib.auth import get_user_model

from accounts.access import has_global_access, line_codes_for
from accounts.models import RoleAssignment
from insurance.models import Contract, InsuranceLine
from organizations.models import Company
from .models import Report


class ReportSubmissionForm(forms.ModelForm):
    summary = forms.CharField(
        label="خلاصه مدیریتی", min_length=10, max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    body = forms.CharField(
        label="متن گزارش", min_length=20,
        widget=forms.Textarea(attrs={"rows": 12}),
    )

    class Meta:
        model = Report
        fields = [
            "title", "report_type", "line_code", "company",
            "period_start", "period_end",
        ]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        all_lines = list(InsuranceLine.choices)
        if user and has_global_access(user):
            allowed_lines = all_lines
            companies = Company.objects.filter(is_active=True)
        else:
            codes = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST) if user else set()
            allowed_lines = all_lines if "*" in codes else [
                choice for choice in all_lines if choice[0] in codes
            ]
            company_ids = Contract.objects.filter(
                line__in=[code for code, _ in allowed_lines],
                is_active=True,
            ).values_list("companies__pk", flat=True)
            companies = Company.objects.filter(pk__in=company_ids, is_active=True).distinct()
        self.fields["line_code"].choices = allowed_lines
        self.fields["company"].queryset = companies.order_by("name")
        if not self.fields["company"].queryset.exists():
            self.fields["company"].required = False

    def clean(self):
        cleaned = super().clean()
        line = cleaned.get("line_code")
        if line and line not in {value for value, _ in self.fields["line_code"].choices}:
            self.add_error("line_code", "این رشته خارج از محدوده انتصاب شماست.")
        return cleaned


class ReportRevisionForm(forms.Form):
    summary = forms.CharField(
        label="خلاصه نسخه جدید", min_length=10, max_length=3000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    body = forms.CharField(
        label="متن اصلاح‌شده گزارش", min_length=20,
        widget=forms.Textarea(attrs={"rows": 12}),
    )
