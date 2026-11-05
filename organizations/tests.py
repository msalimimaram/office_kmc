from datetime import date
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from organizations.models import Company, Person, PersonEmployment

class OrganizationScopeTests(TestCase):
    def test_employee_cannot_list_other_company_people(self):
        a = Company.objects.create(code="A", name="شرکت الف")
        b = Company.objects.create(code="B", name="شرکت ب")
        Person.objects.create(company=a, national_id="1111111111", first_name="علی", last_name="الف", birth_date=date(1990, 1, 1))
        Person.objects.create(company=b, national_id="2222222222", first_name="رضا", last_name="ب", birth_date=date(1991, 1, 1))
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
            first_name="کارمند", last_name="والد", birth_date=date(1988, 1, 1),
        )
        with self.assertRaises(ValidationError):
            Person.objects.create(
                company=company_b, national_id="4444444444",
                first_name="فرد", last_name="تحت تکفل", birth_date=date(2010, 1, 1),
                relationship=Person.Relationship.CHILD, employee=employee,
            )

    def test_person_cannot_have_two_active_company_employments(self):
        person = Person.objects.create(
            company=self.company,
            national_id="9876543210",
            first_name="کارمند",
            last_name="منتقل‌شده",
            birth_date=date(1990, 1, 1),
        )
        other_company = Company.objects.create(code="EMP-B", name="شرکت دوم")
        PersonEmployment.objects.create(
            person=person,
            company=self.company,
            valid_from=date(2020, 1, 1),
            status=PersonEmployment.Status.ACTIVE,
        )
        with self.assertRaises(ValidationError):
            PersonEmployment.objects.create(
                person=person,
                company=other_company,
                valid_from=date(2025, 1, 1),
                status=PersonEmployment.Status.ACTIVE,
            )
