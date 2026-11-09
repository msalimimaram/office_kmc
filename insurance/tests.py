from datetime import date, timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase
from django.utils import timezone
from django.urls import reverse

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
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code=ContractRevision.Status.REJECTED,
            title="ردشده",
            order=3,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=rejected,
            action_code="reject-decision",
            title="رد نسخه",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=rejected,
            action_code="close-rejection",
            title="ثبت نهایی رد",
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
            notice_date=self.today if is_termination else None,
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
        revision.description = "تغییر غیرمجاز نسخه تأییدشده"
        with self.assertRaises(ValidationError):
            revision.save()
        with self.assertRaises(ValidationError):
            ContractRevision.objects.filter(pk=revision.pk).update(description="ویرایش گروهی")
        with self.assertRaises(ValidationError):
            revision.delete()
        with self.assertRaises(ValidationError):
            ContractRevision.objects.bulk_create([revision])

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
        with self.assertRaises(ValidationError):
            ContractRevision.objects.create(
                contract=contract,
                revision_number=2,
                description="نسخه هم‌پوشان غیرمجاز",
                created_by=self.creator,
                status=ContractRevision.Status.PENDING_APPROVAL,
                snapshot=self._snapshot(contract),
                effective_date=effective_date,
            )

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
            service_date=self.today,
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

class ContractSubmissionViewTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.today = today
        self.insurer = Insurer.objects.create(name="بیمه‌گر ثبت قرارداد")
        self.specialist = User.objects.create_user(
            username="contract-submit-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="contract-submit-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.admin = User.objects.create_superuser(
            username="contract-submit-admin",
            email="contract-submit-admin@example.invalid",
            password="StrongPass!2026",
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=InsuranceLine.HEALTH,
            valid_from=today,
            reason="کارشناس درمان",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            valid_from=today,
            reason="رئیس اداره",
        )
        self.client = Client()
        self.client.force_login(self.specialist)

    def _form_data(self, *, line=InsuranceLine.HEALTH):
        start = self.today.isoformat()
        end = (self.today + timedelta(days=365)).isoformat()
        return {
            "code": "CONTRACT-SUBMISSION-001",
            "title": "قرارداد درمان آزمایشی",
            "insurer": str(self.insurer.pk),
            "line": line,
            "start_date": start,
            "end_date": end,
            "effective_date": start,
            "revision_description": "ثبت نسخه اولیه قرارداد برای تأیید",
            "coverage_summary": "پوشش آزمایشی",
            "terms": "شرایط آزمایشی",
        }

    def _create_approval_workflow(self):
        definition = WorkflowDefinition.objects.create(
            code="contract_approval",
            title="گردش تأیید قرارداد",
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
        approved = WorkflowStep.objects.create(
            definition=definition,
            code=ContractRevision.Status.APPROVED,
            title="تأییدشده",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=approved,
            action_code="approve-contract",
            title="تأیید قرارداد",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=approved,
            action_code="finalize-contract",
            title="ثبت نهایی تأیید",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code=ContractRevision.Status.REJECTED,
            title="ردشده",
            order=3,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=rejected,
            action_code="reject-contract",
            title="رد قرارداد",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=rejected,
            action_code="finalize-rejection",
            title="ثبت نهایی رد قرارداد",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()
        return definition

    def test_specialist_submission_creates_inactive_contract_and_routes_revision_to_head(self):
        self._create_approval_workflow()
        response = self.client.post(reverse("contract_create"), self._form_data())

        self.assertEqual(response.status_code, 302)
        contract = Contract.objects.get(code="CONTRACT-SUBMISSION-001")
        revision = contract.revisions.get(revision_number=1)
        from django.contrib.contenttypes.models import ContentType
        from workflow.models import WorkflowCase

        case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(ContractRevision, for_concrete_model=False),
            object_id=str(revision.pk),
        )

        self.assertEqual(contract.status, Contract.Status.DRAFT)
        self.assertFalse(contract.is_active)
        self.assertEqual(revision.status, ContractRevision.Status.PENDING_APPROVAL)
        self.assertEqual(case.current_assignee_id, self.head.pk)

    def test_contract_cannot_be_created_without_active_approval_workflow(self):
        response = self.client.post(reverse("contract_create"), self._form_data())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)
        self.assertContains(response, "contract_approval")

    def test_specialist_cannot_submit_contract_outside_assigned_line(self):
        self._create_approval_workflow()
        response = self.client.post(
            reverse("contract_create"),
            self._form_data(line=InsuranceLine.LIFE),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)


    def test_termination_request_previews_open_claims_and_waits_for_head_decision(self):
        from claims.models import Claim
        from organizations.models import Company, Person

        definition = WorkflowDefinition.objects.create(
            code="contract_termination",
            title="گردش تأیید فسخ",
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
        terminated = WorkflowStep.objects.create(
            definition=definition,
            code=ContractRevision.Status.TERMINATED,
            title="فسخ تأییدشده",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=terminated,
            action_code="approve-termination",
            title="تأیید فسخ",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=terminated,
            action_code="finalize-termination",
            title="ثبت نهایی فسخ",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

        contract = Contract.objects.create(
            code="CONTRACT-TERMINATION-VIEW",
            title="قرارداد مشمول درخواست فسخ",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=100),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        company = Company.objects.create(code="CONTRACT-TERM-CO", name="شرکت قرارداد فسخ")
        person = Person.objects.create(
            company=company,
            national_id="8765432109",
            first_name="بیمه‌شده",
            last_name="دارای پرونده باز",
            birth_date=date(1990, 1, 1),
        )
        Claim.objects.create(
            claim_number="CONTRACT-TERM-OPEN-CLAIM",
            person=person,
            contract=contract,
            insurer=self.insurer,
            service_type="درمان",
            service_date=self.today,
            requested_amount=100,
            status=Claim.Status.UNDER_REVIEW,
        )

        preview = self.client.get(reverse("contract_terminate", args=[contract.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "CONTRACT-TERM-OPEN-CLAIM")

        response = self.client.post(
            reverse("contract_terminate", args=[contract.pk]),
            {
                "effective_date": self.today.isoformat(),
                "notice_date": self.today.isoformat(),
                "reason": "تغییر شرایط قرارداد و درخواست خاتمه با تأیید اداره",
            },
        )
        self.assertEqual(response.status_code, 302)
        revision = contract.revisions.get(is_termination=True)
        self.assertEqual(revision.status, ContractRevision.Status.PENDING_APPROVAL)
        self.assertEqual(revision.termination_reason, "تغییر شرایط قرارداد و درخواست خاتمه با تأیید اداره")
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.ACTIVE)
        self.assertTrue(contract.is_active)
