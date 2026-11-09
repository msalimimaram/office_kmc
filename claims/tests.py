from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organizations.models import Company, Person, PersonEmployment
from claims.models import Claim, ClaimObjection

NATIONAL_ID_A = "1" * 10
NATIONAL_ID_B = "2" * 10
NATIONAL_ID_C = "3" * 10


class ClaimVisibilityTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="A", name="شرکت الف")
        self.company_b = Company.objects.create(code="B", name="شرکت ب")
        self.person_a = Person.objects.create(company=self.company_a, national_id=NATIONAL_ID_A, first_name="علی", last_name="الف", birth_date=date(1990, 1, 1))
        self.person_b = Person.objects.create(company=self.company_b, national_id=NATIONAL_ID_B, first_name="رضا", last_name="ب", birth_date=date(1991, 1, 1))
        self.employee = User.objects.create_user(username=NATIONAL_ID_A, password="StrongPass!2026", must_change_password=False, national_id=NATIONAL_ID_A, role="employee", company=self.company_a)
        self.rep = User.objects.create_user(username="rep-a", password="StrongPass!2026", must_change_password=False, role="subsidiary_rep", company=self.company_a)
        self.admin = User.objects.create_user(username="head", password="StrongPass!2026", must_change_password=False, role="department_head")
        self.insurer_without_link = User.objects.create_user(username="insurer-a", password="StrongPass!2026", must_change_password=False, role="insurer")
        Claim.objects.create(claim_number="CL-1", person=self.person_a, service_type="ویزیت", requested_amount=100)
        Claim.objects.create(claim_number="CL-2", person=self.person_b, service_type="دارو", requested_amount=200)

    def test_employee_sees_own_claims_only(self):
        client = Client()
        client.force_login(self.employee)
        response = client.get(reverse("claim_list"))
        self.assertContains(response, "CL-1")
        self.assertNotContains(response, "CL-2")

    def test_company_rep_sees_only_company_claims(self):
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("claim_list"))
        self.assertContains(response, "CL-1")
        self.assertNotContains(response, "CL-2")

    def test_department_head_can_see_all_claims(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get(reverse("claim_list"))
        self.assertContains(response, "CL-1")
        self.assertContains(response, "CL-2")

    def test_insurer_without_explicit_insurer_link_fails_closed(self):
        client = Client()
        client.force_login(self.insurer_without_link)
        response = client.get(reverse("claim_list"))
        self.assertNotContains(response, "CL-1")
        self.assertNotContains(response, "CL-2")

    def test_new_company_representative_can_see_current_employee_historical_claims(self):
        PersonEmployment.objects.create(
            person=self.person_b,
            company=self.company_b,
            valid_from=date(2026, 1, 1),
            status=PersonEmployment.Status.ACTIVE,
        )
        Claim.objects.create(
            claim_number="CL-HISTORICAL",
            person=self.person_b,
            company_snapshot=self.company_a,
            service_type="خدمت پیش از انتقال",
            requested_amount=300,
        )
        new_company_rep = User.objects.create_user(
            username="rep-b",
            password="StrongPass!2026",
            must_change_password=False,
            role="subsidiary_rep",
            company=self.company_b,
        )
        client = Client()
        client.force_login(new_company_rep)
        response = client.get(reverse("claim_list"))
        self.assertContains(response, "CL-HISTORICAL")

    def test_claim_does_not_guess_current_company_when_employment_history_has_no_date_match(self):
        PersonEmployment.objects.create(
            person=self.person_a,
            company=self.company_b,
            valid_from=date(2010, 1, 1),
            valid_until=date(2020, 12, 31),
            status=PersonEmployment.Status.TRANSFERRED,
        )
        claim = Claim.objects.create(
            claim_number="CL-UNKNOWN-COMPANY",
            person=self.person_a,
            service_date=date(2026, 1, 1),
            service_type="خدمت با شرکت تاریخی نامشخص",
            requested_amount=150,
        )
        self.assertIsNone(claim.company_snapshot_id)
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("claim_list"))
        self.assertNotContains(response, "CL-UNKNOWN-COMPANY")

    def test_national_id_is_globally_unique_across_company_records(self):
        with self.assertRaises(ValidationError):
            Person.objects.create(
                company=self.company_b, national_id=NATIONAL_ID_A,
                first_name="شخص", last_name="شناسه تکراری", birth_date=date(1992, 1, 1),
            )

    def test_claim_cannot_record_negative_or_overpaid_amounts(self):
        with self.assertRaises(ValidationError):
            Claim.objects.create(
                claim_number="CL-NEGATIVE", person=self.person_a,
                service_type="خدمت", requested_amount=-1,
            )
        with self.assertRaises(ValidationError):
            Claim.objects.create(
                claim_number="CL-OVERPAID", person=self.person_a,
                service_type="خدمت", payable_amount=100, paid_amount=101,
            )

    def test_only_employee_or_company_representative_can_submit_claim_objection(self):
        claim = Claim.objects.get(claim_number="CL-1")
        claim.result_sent_at = timezone.now()
        claim.save(update_fields=["result_sent_at", "updated_at"])
        client = Client()
        client.force_login(self.admin)
        response = client.post(reverse("claim_detail", args=[claim.pk]), {"description": "اعتراض آزمایشی"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ClaimObjection.objects.filter(claim=claim).count(), 0)

        client.force_login(self.employee)
        response = client.post(reverse("claim_detail", args=[claim.pk]), {"description": "اعتراض از طرف بیمه‌شده"})
        self.assertEqual(response.status_code, 302)
        objection = ClaimObjection.objects.get(claim=claim)
        self.assertEqual(objection.submitted_by, self.employee)


class ClaimObjectionReviewFlowTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from accounts.models import RoleAssignment
        from insurance.models import Contract, Insurer
        from claims.models import ClaimObjection

        self.company = Company.objects.create(code="OBJ-A", name="شرکت اعتراض")
        self.owner = User.objects.create_user(
            username="objection-owner", password="StrongPass!2026", must_change_password=False,
            role="employee", national_id=NATIONAL_ID_C,
        )
        self.person = Person.objects.create(
            company=self.company, user=self.owner, national_id=NATIONAL_ID_C,
            first_name="کارمند", last_name="اعتراض", birth_date=date(1990, 1, 1),
        )
        self.insurer = Insurer.objects.create(name="بیمه‌گر اعتراض")
        today = timezone.localdate()
        self.contract = Contract.objects.create(
            code="OBJ-CONTRACT", title="قرارداد درمان", insurer=self.insurer,
            line="health", start_date=today - timedelta(days=365), end_date=today + timedelta(days=365),
        )
        self.claim = Claim.objects.create(
            claim_number="OBJ-CLAIM-1", person=self.person, contract=self.contract,
            insurer=self.insurer, service_type="درمان", requested_amount=100,
            result_sent_at=timezone.now() - timedelta(days=1),
        )
        self.objection = ClaimObjection.objects.create(
            claim=self.claim, submitted_by=self.owner, description="اعتراض به مبلغ خسارت",
        )
        self.head = User.objects.create_user(
            username="objection-head", password="StrongPass!2026", must_change_password=False,
            role="department_head",
        )
        self.specialist = User.objects.create_user(
            username="objection-specialist", password="StrongPass!2026", must_change_password=False,
            role="insurance_specialist",
        )
        RoleAssignment.objects.create(
            user=self.specialist, role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health", valid_from=today, is_active=True,
        )

    def test_department_head_can_review_answer_reopen_and_close_objection_with_history(self):
        client = Client()
        client.force_login(self.head)
        detail = client.get(reverse("claim_detail", args=[self.claim.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]))

        first = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.IN_REVIEW, "response": "بررسی آغاز شد",
        })
        self.assertEqual(first.status_code, 302)
        second = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.ANSWERED, "response": "نتیجه بررسی ثبت شد",
        })
        self.assertEqual(second.status_code, 302)
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.status, ClaimObjection.Status.ANSWERED)
        self.assertIn("بررسی آغاز شد", self.objection.response)
        self.assertIn("نتیجه بررسی ثبت شد", self.objection.response)

        close = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.CLOSED, "response": "",
        })
        self.assertEqual(close.status_code, 302)
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.status, ClaimObjection.Status.CLOSED)

    def test_specialist_can_answer_but_cannot_close_objection(self):
        from claims.models import ClaimObjection
        self.objection.status = ClaimObjection.Status.ANSWERED
        self.objection.response = "پاسخ اولیه"
        self.objection.save(update_fields=["status", "response", "updated_at"])

        client = Client()
        client.force_login(self.specialist)
        denied = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.CLOSED, "response": "",
        })
        self.assertEqual(denied.status_code, 403)
        allowed = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.IN_REVIEW, "response": "مدرک تکمیلی درخواست شد",
        })
        self.assertEqual(allowed.status_code, 302)
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.status, ClaimObjection.Status.IN_REVIEW)
        self.assertIn("پاسخ اولیه", self.objection.response)
        self.assertIn("مدرک تکمیلی درخواست شد", self.objection.response)

    def test_employee_cannot_review_own_objection_and_invalid_jump_is_rejected(self):
        client = Client()
        client.force_login(self.owner)
        response = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.CLOSED, "response": "بستن",
        })
        self.assertEqual(response.status_code, 403)

        client.force_login(self.head)
        response = client.post(reverse("claim_objection_review", args=[self.claim.pk, self.objection.pk]), {
            "status": ClaimObjection.Status.CLOSED, "response": "پرش وضعیت",
        })
        self.assertEqual(response.status_code, 403)

    def test_configured_objection_is_routed_through_generic_workflow(self):
        from accounts.models import RoleAssignment
        from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowStep, WorkflowTransition

        definition = WorkflowDefinition.objects.create(
            code="claim_objection",
            title="گردش کار اعتراض خسارت",
            created_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code=ClaimObjection.Status.IN_REVIEW,
            title="بررسی تخصصی",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        answered = WorkflowStep.objects.create(
            definition=definition,
            code=ClaimObjection.Status.ANSWERED,
            title="پاسخ اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=answered,
            action_code="answer-objection",
            title="ثبت پاسخ و ارجاع به اداره",
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=answered,
            action_code="close-objection",
            title="بستن نهایی اعتراض",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        definition.approved_by = self.head
        definition.is_active = True
        definition.save()

        client = Client()
        client.force_login(self.owner)
        submitted = client.post(
            reverse("claim_detail", args=[self.claim.pk]),
            {"description": "درخواست بررسی مجدد مبلغ خسارت"},
        )
        self.assertEqual(submitted.status_code, 302)

        objection = ClaimObjection.objects.exclude(pk=self.objection.pk).get()
        case = WorkflowCase.objects.get(
            definition=definition,
            object_id=str(objection.pk),
        )
        self.assertEqual(case.current_assignee_id, self.specialist.pk)
        objection.refresh_from_db()
        self.assertEqual(objection.status, ClaimObjection.Status.IN_REVIEW)

        client.force_login(self.head)
        legacy_review = client.post(
            reverse("claim_objection_review", args=[self.claim.pk, objection.pk]),
            {"status": ClaimObjection.Status.CLOSED, "response": "بستن مستقیم"},
        )
        self.assertEqual(legacy_review.status_code, 302)
        self.assertEqual(legacy_review.url, reverse("workflow_case_detail", args=[case.pk]))
        objection.refresh_from_db()
        self.assertEqual(objection.status, ClaimObjection.Status.IN_REVIEW)

        client.force_login(self.specialist)
        detail = client.get(reverse("workflow_case_detail", args=[case.pk]))
        self.assertEqual(detail.status_code, 200)




class ManualClaimWorkflowTests(TestCase):
    def setUp(self):
        from datetime import date, timedelta
        from django.core.management import call_command
        from django.utils import timezone
        from accounts.models import RoleAssignment, User
        from insurance.models import Contract, Insurer, InsuranceLine
        from organizations.models import Company, Person

        today = timezone.localdate()
        self.company = Company.objects.create(code="CLM-MAN", name="شرکت خسارت دستی")
        self.insurer = Insurer.objects.create(name="بیمه‌گر خسارت دستی")
        self.contract = Contract.objects.create(
            code="CLM-CONTRACT-1",
            title="قرارداد درمان",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=305),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.contract.companies.add(self.company)
        self.person = Person.objects.create(
            company=self.company,
            national_id="9876543210",
            first_name="بیمه‌شده",
            last_name="آزمایش خسارت",
            birth_date=date(1988, 4, 2),
            mobile="09120001111",
            iban="IR111111111111111111111111",
            is_insured=True,
        )
        self.specialist = User.objects.create_user(
            username="claim-review-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="claim-review-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=InsuranceLine.HEALTH,
            reason="کارشناس رشته برای آزمون ثبت خسارت",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای تصمیم نهایی خسارت",
        )
        call_command("seed_operational_workflows")

    def test_manual_claim_assessment_head_decision_and_result_dispatch(self):
        from datetime import timedelta
        from django.utils import timezone
        from django.contrib.contenttypes.models import ContentType
        from accounts.models import RoleAssignment
        from claims.models import Claim
        from workflow.models import WorkflowCase
        from workflow.services import transition_case

        client = Client()
        client.force_login(self.specialist)
        today = timezone.localdate()
        response = client.post(reverse("claim_create"), {
            "claim_number": "MANUAL-CLAIM-001",
            "source_claim_number": "INSURER-FILE-001",
            "person": str(self.person.pk),
            "contract": str(self.contract.pk),
            "service_date": today.isoformat(),
            "registered_date": today.isoformat(),
            "service_type": "هزینه درمان",
            "requested_amount": "1000000",
            "source_reference": "REF-001",
        })
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(claim_number="MANUAL-CLAIM-001")
        self.assertEqual(claim.status, Claim.Status.UNDER_REVIEW)
        self.assertEqual(claim.insurer_id, self.insurer.pk)
        self.assertEqual(claim.company_snapshot_id, self.company.pk)

        case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(claim, for_concrete_model=False),
            object_id=str(claim.pk),
        )
        self.assertEqual(case.current_assignee_id, self.specialist.pk)

        assessment_response = client.post(reverse("claim_assess", args=[claim.pk]), {
            "assessed_amount": "900000",
            "payable_amount": "800000",
            "assessment_note": "مدارک مالی بررسی شد و مبلغ قابل پرداخت تعیین گردید.",
        })
        self.assertEqual(assessment_response.status_code, 302)
        claim.refresh_from_db()
        self.assertEqual(claim.assessed_by_id, self.specialist.pk)
        self.assertIsNotNone(claim.assessed_at)

        transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="submit_for_decision",
            recipient=self.head,
            note="ارزیابی کامل شد و برای تصمیم نهایی ارجاع می‌شود.",
        )
        transition_case(
            case_id=case.pk,
            actor=self.head,
            action_code="approve",
            note="ارزیابی بررسی و تأیید شد.",
        )
        transition_case(
            case_id=case.pk,
            actor=self.head,
            action_code="finalize",
            note="تصمیم نهایی ثبت شد.",
        )
        claim.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(claim.status, Claim.Status.APPROVED)
        self.assertEqual(case.status, WorkflowCase.Status.CLOSED)

        client.force_login(self.head)
        send_response = client.post(reverse("claim_result_send", args=[claim.pk]))
        self.assertEqual(send_response.status_code, 302)
        claim.refresh_from_db()
        self.assertIsNotNone(claim.result_sent_at)
        self.assertEqual(claim.result_sent_by_id, self.head.pk)
        self.assertEqual(
            claim.objection_deadline,
            claim.result_sent_at + timedelta(days=60),
        )

    def test_manual_claim_form_rejects_contract_outside_service_date(self):
        from datetime import timedelta
        from django.utils import timezone

        client = Client()
        client.force_login(self.specialist)
        future_service_date = timezone.localdate() + timedelta(days=500)
        response = client.post(reverse("claim_create"), {
            "claim_number": "MANUAL-CLAIM-002",
            "person": str(self.person.pk),
            "contract": str(self.contract.pk),
            "service_date": future_service_date.isoformat(),
            "registered_date": timezone.localdate().isoformat(),
            "service_type": "هزینه درمان",
            "requested_amount": "1000000",
            "source_reference": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Claim.objects.filter(claim_number="MANUAL-CLAIM-002").exists())
        self.assertContains(response, "خارج از بازه اعتبار قرارداد")


    def test_only_insurer_can_declare_duplicate(self):
        from accounts.models import RoleAssignment, User
        from claims.models import Claim
        from django.utils import timezone

        claim = Claim.objects.create(
            claim_number="DUPLICATE-DECL-001",
            source_claim_number="INS-FILE-77",
            person=self.person,
            company_snapshot=self.company,
            insurer=self.insurer,
            contract=self.contract,
            contract_number_snapshot=self.contract.code,
            service_date=timezone.localdate(),
            registered_date=timezone.localdate(),
            service_type="هزینه درمان",
            requested_amount="500000",
        )
        insurer_rep = User.objects.create_user(
            username="claim-duplicate-insurer-rep",
            password=None,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=insurer_rep,
            role=RoleAssignment.Role.INSURER,
            insurer=self.insurer,
            line_code=self.contract.line,
            reason="نماینده بیمه‌گر برای اعلام تکراری بودن",
        )

        client = Client()
        client.force_login(self.specialist)
        forbidden = client.post(reverse("claim_duplicate_declare", args=[claim.pk]), {
            "source_duplicate_reference": "INS-FILE-1",
            "source_duplicate_note": "این پرونده در سامانه بیمه‌گر تکراری اعلام شده است.",
        })
        self.assertEqual(forbidden.status_code, 403)

        client.force_login(insurer_rep)
        response = client.post(reverse("claim_duplicate_declare", args=[claim.pk]), {
            "source_duplicate_reference": "INS-FILE-1",
            "source_duplicate_note": "بیمه‌گر پس از تطبیق پرونده، آن را تکراری اعلام می‌کند.",
        })
        self.assertEqual(response.status_code, 302)
        claim.refresh_from_db()
        self.assertEqual(claim.source_duplicate_status, Claim.DuplicateStatus.DECLARED_DUPLICATE)
        self.assertEqual(claim.source_duplicate_reported_by_id, insurer_rep.pk)
