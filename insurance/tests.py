from datetime import date, timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import RoleAssignment, User
from insurance.models import Contract, ContractRevision, Insurer, InsuranceLine
from workflow.models import WorkflowDefinition, WorkflowStep, WorkflowTransition
from workflow.services import start_workflow, transition_case


class ContractValidationTests(TestCase):
    def test_contract_end_date_cannot_precede_start_date(self):
        insurer = Insurer.objects.create(name="بیمه‌گر آزمایشی")
        with self.assertRaises(ValidationError):
            Contract.objects.create(
                code="CONTRACT-INVALID-DATES",
                title="قرارداد آزمایشی",
                insurer=insurer,
                line=InsuranceLine.HEALTH,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 31),
            )

    def test_valid_contract_dates_are_accepted(self):
        insurer = Insurer.objects.create(name="بیمه‌گر معتبر")
        contract = Contract.objects.create(
            code="CONTRACT-VALID-DATES",
            title="قرارداد معتبر",
            insurer=insurer,
            line=InsuranceLine.HEALTH,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        self.assertEqual(contract.end_date, date(2026, 12, 31))


class InsuranceAdminBoundaryTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = User.objects.create_user(
            username="insurance-admin-unassigned",
            password="StrongPass!2026",
            is_staff=True,
            must_change_password=False,
        )
        self.operator = User.objects.create_user(
            username="insurance-admin-global",
            password="StrongPass!2026",
            is_staff=True,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.operator,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه در آزمون مرز مدیریت بیمه",
        )

    def _request(self, user):
        request = self.factory.get("/admin/")
        request.user = user
        return request

    def test_contract_and_revision_admin_are_read_only_even_for_global_operator(self):
        request = self._request(self.operator)
        for model in (Contract, ContractRevision):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.has_module_permission(request))
                self.assertTrue(model_admin.has_view_permission(request))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))

    def test_unassigned_staff_cannot_open_insurance_admin_modules(self):
        request = self._request(self.staff)
        for model in (Insurer, Contract, ContractRevision):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_module_permission(request))
                self.assertFalse(model_admin.has_view_permission(request))

    def test_insurer_reference_can_be_managed_only_by_global_operator_and_never_deleted(self):
        global_request = self._request(self.operator)
        staff_request = self._request(self.staff)
        model_admin = admin.site._registry[Insurer]

        self.assertTrue(model_admin.has_add_permission(global_request))
        self.assertTrue(model_admin.has_change_permission(global_request))
        self.assertFalse(model_admin.has_delete_permission(global_request))
        self.assertFalse(model_admin.has_add_permission(staff_request))
        self.assertFalse(model_admin.has_change_permission(staff_request))

class ContractWorkflowLifecycleTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.today = today
        self.insurer = Insurer.objects.create(name="بیمه‌گر چرخه قرارداد")
        self.creator = User.objects.create_user(
            username="contract-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="contract-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.admin = User.objects.create_superuser(
            username="contract-system-admin",
            email="contract-admin@example.invalid",
            password="StrongPass!2026",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            valid_from=today,
            reason="رئیس اداره برای آزمون گردش قرارداد",
        )

    def _contract(self, *, code, start_date=None, end_date=None, active=False):
        start_date = start_date or self.today - timedelta(days=1)
        end_date = end_date or self.today + timedelta(days=90)
        return Contract.objects.create(
            code=code,
            title="قرارداد آزمایشی چرخه عمر",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=start_date,
            end_date=end_date,
            status=Contract.Status.ACTIVE if active else Contract.Status.DRAFT,
            is_active=active,
        )

    def _snapshot(self, contract):
        return {
            "code": contract.code,
            "title": contract.title,
            "insurer_id": contract.insurer_id,
            "line": contract.line,
            "start_date": contract.start_date.isoformat(),
            "end_date": contract.end_date.isoformat(),
            "coverage_summary": "پوشش آزمایشی",
            "terms": "شرایط آزمایشی",
            "company_ids": [],
        }

    def _workflow(self, *, code, final_status):
        definition = WorkflowDefinition.objects.create(
            code=code,
            title=f"گردش کار {code}",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code=ContractRevision.Status.PENDING_APPROVAL,
            title="در انتظار تأیید",
            order=1,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            is_initial=True,
        )
        final = WorkflowStep.objects.create(
            definition=definition,
            code=final_status,
            title="تصمیم نهایی",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=final,
            action_code="record-decision",
            title="ثبت تصمیم",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=final,
            action_code="close-decision",
            title="ثبت نهایی تصمیم",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()
        return definition

    def _approve_revision(self, *, contract, code, final_status, effective_date, is_termination=False):
        definition = self._workflow(code=code, final_status=final_status)
        revision = ContractRevision.objects.create(
            contract=contract,
            revision_number=1,
            description="نسخه اولیه/تغییر آزمایشی",
            created_by=self.creator,
            status=ContractRevision.Status.PENDING_APPROVAL,
            snapshot=self._snapshot(contract),
            effective_date=effective_date,
            is_termination=is_termination,
            termination_reason="درخواست خاتمه طبق تصمیم سازمان" if is_termination else "",
        )
        case = start_workflow(
            obj=revision,
            code=code,
            actor=self.creator,
            assignee=self.head,
        )
        revision.refresh_from_db()
        self.assertEqual(revision.status, ContractRevision.Status.PENDING_APPROVAL)
        case = transition_case(
            case_id=case.pk,
            actor=self.head,
            action_code="record-decision",
            recipient=self.head,
        )
        revision.refresh_from_db()
        # A decision step alone is not enough; final close commits the domain change.
        self.assertEqual(revision.status, ContractRevision.Status.PENDING_APPROVAL)
        transition_case(
            case_id=case.pk,
            actor=self.head,
            action_code="close-decision",
        )
        revision.refresh_from_db()
        contract.refresh_from_db()
        return revision, contract

    def test_contract_is_activated_only_after_authorized_workflow_closes(self):
        contract = self._contract(code="CONTRACT-WF-APPROVAL")
        revision, contract = self._approve_revision(
            contract=contract,
            code="contract_approval",
            final_status=ContractRevision.Status.APPROVED,
            effective_date=self.today,
        )

        self.assertEqual(revision.status, ContractRevision.Status.APPROVED)
        self.assertEqual(revision.approved_by, self.head)
        self.assertIsNotNone(revision.approved_at)
        self.assertIsNotNone(revision.applied_at)
        self.assertEqual(contract.status, Contract.Status.ACTIVE)
        self.assertTrue(contract.is_active)
        self.assertEqual(contract.coverage_summary, "پوشش آزمایشی")

    def test_future_effective_contract_waits_then_daily_command_activates_it(self):
        effective_date = self.today + timedelta(days=2)
        contract = self._contract(
            code="CONTRACT-WF-FUTURE",
            start_date=effective_date,
            end_date=effective_date + timedelta(days=90),
        )
        revision, contract = self._approve_revision(
            contract=contract,
            code="contract_approval",
            final_status=ContractRevision.Status.APPROVED,
            effective_date=effective_date,
        )
        self.assertEqual(contract.status, Contract.Status.APPROVED)
        self.assertFalse(contract.is_active)
        self.assertIsNone(revision.applied_at)

        from django.core.management import call_command
        from unittest.mock import patch

        with patch("django.utils.timezone.localdate", return_value=effective_date):
            call_command("apply_due_contract_revisions", verbosity=0)

        contract.refresh_from_db()
        revision.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.ACTIVE)
        self.assertTrue(contract.is_active)
        self.assertIsNotNone(revision.applied_at)

    def test_approved_termination_keeps_contract_claim_history_open(self):
        from claims.models import Claim
        from organizations.models import Company, Person

        contract = self._contract(code="CONTRACT-WF-TERMINATION", active=True)
        company = Company.objects.create(code="TERM-COMP", name="شرکت آزمون فسخ")
        person = Person.objects.create(
            company=company,
            national_id="9876543210",
            first_name="کارمند",
            last_name="دارای خسارت",
            birth_date=date(1990, 1, 1),
        )
        claim = Claim.objects.create(
            claim_number="CLAIM-OPEN-AT-TERMINATION",
            person=person,
            contract=contract,
            insurer=self.insurer,
            service_type="خدمت درمانی",
            service_date=self.today - timedelta(days=2),
            requested_amount=100,
            status=Claim.Status.UNDER_REVIEW,
        )

        revision, contract = self._approve_revision(
            contract=contract,
            code="contract_termination",
            final_status=ContractRevision.Status.TERMINATED,
            effective_date=self.today,
            is_termination=True,
        )

        claim.refresh_from_db()
        self.assertEqual(revision.status, ContractRevision.Status.TERMINATED)
        self.assertEqual(contract.status, Contract.Status.TERMINATED)
        self.assertFalse(contract.is_active)
        self.assertEqual(contract.end_date, self.today)
        self.assertEqual(claim.status, Claim.Status.UNDER_REVIEW)
