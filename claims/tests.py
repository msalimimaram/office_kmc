from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organizations.models import Company, Person
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
