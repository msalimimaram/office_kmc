from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.access import active_assignments
from accounts.models import RoleAssignment, User
from insurance.models import Insurer, InsuranceLine
from organizations.models import Company, PersonChangeRequest
from workflow.models import WorkflowDefinition
from .models import WorkDelegation


class WorkDelegationForm(forms.ModelForm):
    class Meta:
        model = WorkDelegation
        fields = [
            "workflow_code", "item_type", "delegate_role", "delegate_to",
            "company", "insurer", "line_code", "valid_from", "valid_until", "reason",
        ]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        codes = list(
            WorkflowDefinition.objects.filter(is_active=True)
            .order_by("code", "-version").values_list("code", flat=True).distinct()
        )
        self.fields["workflow_code"].choices = [("", "انتخاب گردش‌کار")] + [
            (code, code.replace("_", " ")) for code in codes
        ]
        self.fields["item_type"].choices = [("", "تمام زیرنوع‌ها")] + list(PersonChangeRequest.ChangeType.choices)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["insurer"].queryset = Insurer.objects.filter(is_active=True).order_by("name")
        self.fields["line_code"].choices = [("", "همه رشته‌ها")] + list(InsuranceLine.choices)
        self._refresh_recipients()

    def _refresh_recipients(self):
        role = self.data.get("delegate_role") or self.initial.get("delegate_role") or RoleAssignment.Role.INSURANCE_SPECIALIST
        today = timezone.localdate()
        assignments = RoleAssignment.objects.filter(
            role=role, is_active=True, valid_from__lte=today,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        company_id = self.data.get("company") or self.initial.get("company")
        insurer_id = self.data.get("insurer") or self.initial.get("insurer")
        line_code = self.data.get("line_code") or self.initial.get("line_code")
        if role == RoleAssignment.Role.INSURANCE_SPECIALIST and line_code:
            assignments = assignments.filter(line_code__in=[line_code, "*"])
        elif role == RoleAssignment.Role.SUBSIDIARY_REP and company_id:
            assignments = assignments.filter(company_id=company_id)
        elif role == RoleAssignment.Role.INSURER_REP and insurer_id:
            assignments = assignments.filter(insurer_id=insurer_id)
        self.fields["delegate_to"].queryset = User.objects.filter(
            pk__in=assignments.values("user_id"), is_active=True,
        ).order_by("last_name", "first_name", "username").distinct()

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get("workflow_code")
        role = cleaned.get("delegate_role")
        delegate = cleaned.get("delegate_to")
        company = cleaned.get("company")
        insurer = cleaned.get("insurer")
        line_code = cleaned.get("line_code")
        if code and not WorkflowDefinition.objects.filter(code=code, is_active=True).exists():
            self.add_error("workflow_code", "گردش‌کار انتخاب‌شده فعال نیست.")
        if code != "person_change" and cleaned.get("item_type"):
            self.add_error("item_type", "زیرنوع فقط برای گردش‌کار اصلاح اطلاعات اشخاص قابل انتخاب است.")
        if role == RoleAssignment.Role.INSURANCE_SPECIALIST:
            if not line_code:
                self.add_error("line_code", "رشته کارشناس باید مشخص باشد.")
            if delegate and line_code and not active_assignments(delegate).filter(
                role=role, line_code__in=[line_code, "*"]
            ).exists():
                self.add_error("delegate_to", "گیرنده در رشته انتخاب‌شده انتصاب فعال ندارد.")
        elif role == RoleAssignment.Role.SUBSIDIARY_REP:
            if not company:
                self.add_error("company", "شرکت نماینده باید مشخص باشد.")
            if delegate and company and not active_assignments(delegate).filter(
                role=role, company=company
            ).exists():
                self.add_error("delegate_to", "گیرنده نماینده فعال این شرکت نیست.")
        elif role == RoleAssignment.Role.INSURER_REP:
            if not insurer:
                self.add_error("insurer", "بیمه‌گر باید مشخص باشد.")
            if delegate and insurer and not active_assignments(delegate).filter(
                role=role, insurer=insurer
            ).exists():
                self.add_error("delegate_to", "گیرنده نماینده فعال این بیمه‌گر نیست.")
        return cleaned
