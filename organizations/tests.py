from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from organizations.models import Company, Person

class OrganizationScopeTests(TestCase):
    def test_employee_cannot_list_other_company_people(self):
        a = Company.objects.create(code="A", name="شرکت الف")
        b = Company.objects.create(code="B", name="شرکت ب")
        Person.objects.create(company=a, national_id="1111111111", first_name="علی", last_name="الف")
        Person.objects.create(company=b, national_id="2222222222", first_name="رضا", last_name="ب")
        user = User.objects.create_user(username="1111111111", password="StrongPass!2026", must_change_password=False, national_id="1111111111", role="employee", company=a)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("people_list"))
        self.assertContains(response, "علی")
        self.assertNotContains(response, "رضا")

    def test_dependent_cannot_belong_to_a_different_company_than_employee(self):
        from django.core.exceptions import ValidationError

        company_a = Company.objects.create(code="DEP-A", name="شرکت والد")
        company_b = Company.objects.create(code="DEP-B", name="شرکت وابسته")
        employee = Person.objects.create(
            company=company_a, national_id="3333333333",
            first_name="کارمند", last_name="والد",
        )
        with self.assertRaises(ValidationError):
            Person.objects.create(
                company=company_b, national_id="4444444444",
                first_name="فرد", last_name="تحت تکفل",
                relationship=Person.Relationship.CHILD, employee=employee,
            )
