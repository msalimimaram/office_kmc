from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserNotification
from organizations.models import Company
from workflow.models import WorkflowDefinition, WorkflowStep
from workflow.services import is_delegated_assignee, resolve_initial_assignee, start_workflow, transition_case
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowTransition

from .models import WorkDelegation
from .services import update_delegation_status


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
        self.definition.approved_by = self.head
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

    def test_delegate_can_receive_and_act_on_scoped_initial_work(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=78,
            created_by=self.head,
            approved_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        review = WorkflowStep.objects.create(
            definition=definition,
            code="head_review",
            title="بررسی رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=review,
            action_code="refer_to_head",
            title="ارجاع برای تصمیم",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.is_active = True
        definition.save()
        request = ServiceRequest.objects.create(
            reference="DELEGATION-REQ-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست آزمایشی",
            description="آزمون تفویض اختیار",
            is_confidential=True,
        )
        rule = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="رسیدگی تخصصی به درخواست‌های درمانی",
            valid_from=timezone.localdate(),
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=request,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=request,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(assignee, self.specialist)
        self.assertEqual(case.delegation, rule)
        self.assertTrue(is_delegated_assignee(case, self.specialist))
        transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="refer_to_head",
            recipient=self.head,
            note="بررسی اولیه انجام شد.",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_assignee, self.head)
        self.assertIsNone(case.delegation_id)
        self.assertFalse(is_delegated_assignee(case, self.specialist))
        self.assertEqual(
            case.events.order_by("-pk").first().metadata["delegation_id"],
            rule.pk,
        )

    def test_more_specific_rule_wins_over_broader_rule(self):
        backup = User.objects.create_user(
            username="delegation.health.backup", password="TestPass!23456"
        )
        RoleAssignment.objects.create(
            user=backup,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=timezone.localdate(),
        )
        WorkDelegation.objects.create(
            workflow_code="person_change",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            line_code="health",
            reason="تفویض عمومی رشته درمان",
            valid_from=timezone.localdate(),
        )
        specific = WorkDelegation.objects.create(
            workflow_code="person_change",
            item_type="iban",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=backup,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض تخصصی اصلاح شبا در این شرکت",
            valid_from=timezone.localdate(),
        )

        assignee, matched = resolve_initial_assignee(
            definition=self.definition,
            company_id=self.company.pk,
            line_code="health",
            item_type="iban",
            return_delegation=True,
        )

        self.assertEqual(assignee, backup)
        self.assertEqual(matched, specific)

    def test_revoking_specific_rule_routes_open_cases_to_broader_valid_rule(self):
        backup = User.objects.create_user(
            username="delegation.health.backup", password="TestPass!23456"
        )
        RoleAssignment.objects.create(
            user=backup,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=timezone.localdate(),
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=79,
            created_by=self.head,
            approved_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        broad = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            line_code="health",
            reason="تفویض عمومی درخواست‌های درمانی",
            valid_from=timezone.localdate(),
        )
        specific = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=backup,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض اختصاصی این شرکت",
            valid_from=timezone.localdate(),
        )
        request = ServiceRequest.objects.create(
            reference="DELEGATION-REQ-REVOKE",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست آزمایش برگشت تفویض",
            description="آزمون جایگزینی قانون تفویض",
            is_confidential=True,
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=request,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=request,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(case.current_assignee, backup)
        self.assertEqual(case.delegation, specific)

        update_delegation_status(
            delegation_id=specific.pk,
            actor=self.head,
            action="revoke",
            reason="تغییر در تقسیم مسئولیت‌ها",
        )

        case.refresh_from_db()
        self.assertEqual(case.current_assignee, self.specialist)
        self.assertEqual(case.delegation, broad)
        self.assertTrue(
            case.events.filter(
                action_code="delegation_route",
                metadata__delegation_id=broad.pk,
            ).exists()
        )

    def test_recipient_inbox_shows_assigned_work_and_creates_notification(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=80,
            created_by=self.head,
            approved_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        rule = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="رسیدگی درخواست‌های درمانی این شرکت",
            valid_from=timezone.localdate(),
        )
        item = ServiceRequest.objects.create(
            reference="DELEGATION-INBOX-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست نمایشی صندوق گیرنده",
            description="آزمون نمایش در پنل گیرنده",
            is_confidential=True,
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=item,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=item,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(case.delegation, rule)
        self.assertTrue(UserNotification.objects.filter(
            recipient=self.specialist,
            target_url=reverse("workflow_case_detail", args=[case.pk]),
        ).exists())

        client = Client()
        client.force_login(self.specialist)
        inbox = client.get(reverse("delegation_inbox"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "کارهای تفویض‌شده به من")
        self.assertContains(inbox, "درخواست نمایشی صندوق گیرنده")
        self.assertContains(inbox, "درخواست درمان")
        dashboard = client.get(reverse("dashboard"))
        self.assertContains(dashboard, reverse("delegation_inbox"))

    def test_unrelated_user_cannot_open_or_see_delegation_inbox(self):
        unrelated = User.objects.create_user(
            username="delegation.unrelated",
            password="TestPass!23456",
            must_change_password=False,
        )
        client = Client()
        client.force_login(unrelated)
        inbox = client.get(reverse("delegation_inbox"))
        self.assertEqual(inbox.status_code, 403)
        dashboard = client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, reverse("delegation_inbox"))

    def test_global_manager_can_open_delegation_management(self):
        client = Client()
        client.force_login(self.head)
        response = client.get(reverse("delegation_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مدیریت تفویض اختیار")

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
