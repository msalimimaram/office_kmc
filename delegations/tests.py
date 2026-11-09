from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import RoleAssignment
from organizations.models import Company
from workflow.models import WorkflowDefinition, WorkflowStep
from workflow.services import resolve_initial_assignee

from .models import WorkDelegation


User = get_user_model()


class DelegationRoutingTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.head = User.objects.create_user(username="delegation.head", password="TestPass!23456")
        RoleAssignment.objects.create(
            user=self.head, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            is_active=True, valid_from=today,
        )
        self.company = Company.objects.create(code="DELEGATION-CO", name="شرکت آزمون تفویض")
        self.representative = User.objects.create_user(username="delegation.rep", password="TestPass!23456")
        RoleAssignment.objects.create(
            user=self.representative, role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company, line_code="health", is_active=True, valid_from=today,
        )
        self.specialist = User.objects.create_user(username="delegation.health", password="TestPass!23456")
        RoleAssignment.objects.create(
            user=self.specialist, role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health", is_active=True, valid_from=today,
        )
        self.definition = WorkflowDefinition.objects.create(
            code="person_change", title="اصلاح اطلاعات", version=77, created_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=self.definition, code="company_review",
            title="بررسی اولیه", order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP], is_initial=True,
        )
        self.definition.is_active = True
        self.definition.save()

    def test_iban_delegation_routes_only_matching_change_type_to_specialist(self):
        rule = WorkDelegation.objects.create(
            workflow_code="person_change", item_type="iban",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist, granted_by=self.head,
            company=self.company, line_code="health",
            reason="رسیدگی تخصصی به تمام اصلاح‌های شبا",
            valid_from=timezone.localdate(),
        )
        assignee, matched = resolve_initial_assignee(
            definition=self.definition, company_id=self.company.pk,
            line_code="health", item_type="iban", return_delegation=True,
        )
        self.assertEqual(assignee, self.specialist)
        self.assertEqual(matched, rule)

    def test_unrelated_person_change_keeps_normal_company_assignment(self):
        assignee, matched = resolve_initial_assignee(
            definition=self.definition, company_id=self.company.pk,
            line_code="health", item_type="mobile", return_delegation=True,
        )
        self.assertEqual(assignee, self.representative)
        self.assertIsNone(matched)

    def test_ambiguous_delegation_rules_are_blocked(self):
        common = {
            "workflow_code": "person_change",
            "item_type": "iban",
            "delegate_role": RoleAssignment.Role.INSURANCE_SPECIALIST,
            "delegate_to": self.specialist,
            "granted_by": self.head,
            "line_code": "health",
            "reason": "تفویض آزمون",
            "valid_from": timezone.localdate(),
        }
        WorkDelegation.objects.create(**common, company=self.company)
        WorkDelegation.objects.create(**common, company=self.company)
        with self.assertRaises(ValidationError):
            resolve_initial_assignee(
                definition=self.definition, company_id=self.company.pk,
                line_code="health", item_type="iban",
            )
