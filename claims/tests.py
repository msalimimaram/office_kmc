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
