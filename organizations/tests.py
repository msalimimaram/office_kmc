from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import RoleAssignment, User
from organizations.models import Company, CompanyLeadershipTitle, Person, PersonEmployment

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
            company=Company.objects.create(code="EMP-A", name="شرکت اول"),
            national_id="9876543210",
            first_name="کارمند",
            last_name="منتقل‌شده",
            birth_date=date(1990, 1, 1),
        )
        other_company = Company.objects.create(code="EMP-B", name="شرکت دوم")
        PersonEmployment.objects.create(
            person=person,
            company=Company.objects.get(code="EMP-A"),
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



class CompanyLeadershipTitleFlowTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="LEAD-A", name="شرکت سمت الف")
        self.company_b = Company.objects.create(code="LEAD-B", name="شرکت سمت ب")
        self.person_a = Person.objects.create(
            company=self.company_a,
            national_id="5555555555",
            first_name="مدیر",
            last_name="شرکت الف",
            birth_date=date(1980, 1, 1),
        )
        self.person_b = Person.objects.create(
            company=self.company_b,
            national_id="6666666666",
            first_name="مدیر",
            last_name="شرکت ب",
            birth_date=date(1981, 1, 1),
        )
        self.rep = User.objects.create_user(
            username="leadership-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="leadership-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            reason="نماینده شرکت الف برای آزمون",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای آزمون",
        )
        self.other_company_title = CompanyLeadershipTitle.objects.create(
            company=self.company_b,
            person=self.person_b,
            title="مدیرعامل",
            valid_from=date(2025, 1, 1),
            declared_by=self.head,
        )

    def test_company_representative_can_declare_title_for_own_company_and_title_appears_in_people_list(self):
        client = Client()
        client.force_login(self.rep)
        response = client.post(reverse("company_leadership_titles"), {
            "company": str(self.company_a.pk),
            "person": str(self.person_a.pk),
            "title": "معاون مدیرعامل",
            "valid_from": "2026-01-01",
            "valid_until": "2026-12-31",
        })
        self.assertEqual(response.status_code, 302)
        title = CompanyLeadershipTitle.objects.get(
            company=self.company_a,
            person=self.person_a,
            title="معاون مدیرعامل",
        )
        self.assertEqual(title.declared_by_id, self.rep.pk)

        people = client.get(reverse("people_list"))
        self.assertEqual(people.status_code, 200)
        self.assertContains(people, "معاون مدیرعامل")
        self.assertNotContains(people, "مدیرعامل")

    def test_company_representative_cannot_forge_another_company_in_post(self):
        client = Client()
        client.force_login(self.rep)
        response = client.post(reverse("company_leadership_titles"), {
            "company": str(self.company_b.pk),
            "person": str(self.person_b.pk),
            "title": "عنوان جعلی",
            "valid_from": "2026-01-01",
            "valid_until": "2026-12-31",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            CompanyLeadershipTitle.objects.filter(title="عنوان جعلی").exists()
        )

    def test_company_representative_sees_only_titles_within_assigned_company_scope(self):
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("company_leadership_titles"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "شرکت ب")
        self.assertNotContains(response, "مدیرعامل")

    def test_unassigned_employee_cannot_open_leadership_title_management(self):
        employee = User.objects.create_user(
            username="leadership-employee",
            password="StrongPass!2026",
            must_change_password=False,
            role="employee",
        )
        client = Client()
        client.force_login(employee)
        response = client.get(reverse("company_leadership_titles"))
        self.assertEqual(response.status_code, 403)
