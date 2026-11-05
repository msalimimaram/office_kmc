from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.access import company_ids_for, has_global_access, has_role, insurer_ids_for, line_codes_for
from accounts.models import RoleAssignment, PositionAssignment
from insurance.models import Contract, Insurer
from organizations.models import Company
from core.uploads import validate_uploaded_file
from .models import Correspondence


User = get_user_model()


def _eligible_internal_assignees():
    today = timezone.localdate()
    role_users = RoleAssignment.objects.filter(
        is_active=True,
        valid_from__lte=today,
        role__in=[
            RoleAssignment.Role.SYSTEM_ADMIN,
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
        ],
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).values_list("user_id", flat=True)
    position_users = PositionAssignment.objects.filter(
        is_active=True,
        valid_from__lte=today,
        position__level__in=[
            PositionAssignment.position.field.related_model.Level.SUPERVISOR,
            PositionAssignment.position.field.related_model.Level.RESPONSIBLE,
        ],
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).values_list("user_id", flat=True)
    return User.objects.filter(is_active=True).filter(
        Q(pk__in=role_users) | Q(pk__in=position_users)
    ).distinct().order_by("last_name", "first_name", "username")


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

    def __init__(self, *args, user, active_company_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.active_company_id = active_company_id
        self.fields["company"].queryset = Company.objects.filter(is_active=True)
        self.fields["insurer"].queryset = Insurer.objects.filter(is_active=True)
        self.fields["contract"].queryset = Contract.objects.filter(is_active=True).select_related("insurer")
        self.fields["assigned_to"].queryset = _eligible_internal_assignees()

        if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST) and not has_global_access(user):
            self.fields.pop("is_confidential")
            specialist_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
            if "*" in specialist_lines:
                pass
            elif specialist_lines:
                self.fields["contract"].queryset = self.fields["contract"].queryset.filter(line__in=specialist_lines)
                self.fields["company"].queryset = self.fields["company"].queryset.filter(insurance_contracts__line__in=specialist_lines).distinct()
            else:
                self.fields["contract"].queryset = Contract.objects.none()
                self.fields["company"].queryset = Company.objects.none()

        if has_role(user, RoleAssignment.Role.SUBSIDIARY_REP):
            company_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            self.fields.pop("company")
            self.fields.pop("assigned_to")
            self.fields.pop("is_confidential")
            self.fields["contract"].queryset = self.fields["contract"].queryset.filter(companies__in=company_ids).distinct()

        insurer_ids = insurer_ids_for(user)
        if has_role(user, RoleAssignment.Role.INSURER_REP):
            self.fields.pop("assigned_to")
            self.fields.pop("is_confidential")
            self.fields["insurer"].queryset = Insurer.objects.filter(pk__in=insurer_ids)
            if len(insurer_ids) == 1:
                self.fields["insurer"].initial = next(iter(insurer_ids))
                self.fields["insurer"].disabled = True
            self.fields["contract"].queryset = self.fields["contract"].queryset.filter(insurer_id__in=insurer_ids)
            self.fields["company"].queryset = self.fields["company"].queryset.filter(
                insurance_contracts__insurer_id__in=insurer_ids
            ).distinct()

        self.fields["attachment"].required = False

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        if company is None and self.active_company_id:
            company = Company.objects.filter(pk=self.active_company_id).first()
        insurer = cleaned.get("insurer")
        contract = cleaned.get("contract")

        if has_role(self.user, RoleAssignment.Role.SUBSIDIARY_REP):
            company_ids = company_ids_for(self.user, role=RoleAssignment.Role.SUBSIDIARY_REP)
            if not company or company.pk not in company_ids:
                if "company" in self.fields:
                    self.add_error("company", "شرکت فعال نمایندگی مشخص یا مجاز نیست.")
                else:
                    self.add_error(None, "شرکت فعال نمایندگی مشخص یا مجاز نیست.")
        if has_role(self.user, RoleAssignment.Role.INSURER_REP):
            insurer_ids = insurer_ids_for(self.user)
            if not insurer or insurer.pk not in insurer_ids:
                self.add_error("insurer", "شرکت بیمه‌گر متصل به حساب معتبر نیست.")
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
