from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from organizations.models import Company, Person
from claims.models import Claim


class ClaimVisibilityTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="A", name="شرکت الف")
        self.company_b = Company.objects.create(code="B", name="شرکت ب")
        self.person_a = Person.objects.create(company=self.company_a, national_id="1111111111", first_name="علی", last_name="الف")
        self.person_b = Person.objects.create(company=self.company_b, national_id="2222222222", first_name="رضا", last_name="ب")
        self.employee = User.objects.create_user(username="1111111111", password="StrongPass!2026", must_change_password=False, national_id="1111111111", role="employee", company=self.company_a)
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
