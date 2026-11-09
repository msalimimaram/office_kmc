from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import RoleAssignment, User
from organizations.models import Company, CompanyLeadershipTitle, Person, PersonEmployment
from requests_portal.models import ServiceRequest

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



class PersonAdminChangeProtectionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="ADM-PER", name="شرکت حفاظت اطلاعات")
        self.person = Person.objects.create(
            company=self.company,
            national_id="1234509876",
            first_name="شخص",
            last_name="آزمایشی",
            birth_date=date(1990, 1, 1),
            mobile="09120000000",
            iban="IR120000000000000000000000",
        )
        self.admin = User.objects.create_user(
            username="person-admin",
            password="StrongPass!2026",
            role="system_admin",
            is_staff=True,
            must_change_password=False,
        )
        self.client.force_login(self.admin)

    def test_global_operator_can_view_and_create_person_but_cannot_edit_or_delete_existing_person(self):
        changelist = reverse("admin:organizations_person_changelist")
        detail = reverse("admin:organizations_person_change", args=[self.person.pk])
        add = reverse("admin:organizations_person_add")
        delete = reverse("admin:organizations_person_delete", args=[self.person.pk])

        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.get(add).status_code, 200)
        self.assertEqual(self.client.get(delete).status_code, 403)

    def test_admin_post_cannot_bypass_person_change_workflow(self):
        detail = reverse("admin:organizations_person_change", args=[self.person.pk])
        response = self.client.post(detail, {
            "mobile": "09129999999",
            "iban": "IR990000000000000000000000",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 403)
        self.person.refresh_from_db()
        self.assertEqual(self.person.mobile, "09120000000")
        self.assertEqual(self.person.iban, "IR120000000000000000000000")


class SpecialistPeopleScopeTests(TestCase):
    def test_specialist_sees_only_people_linked_to_assigned_non_confidential_work(self):
        company = Company.objects.create(code="SPEC-PEOPLE", name="شرکت حوزه کارشناس")
        visible_person = Person.objects.create(
            company=company,
            national_id="7777777777",
            first_name="فرد",
            last_name="مرتبط",
            birth_date=date(1990, 1, 1),
        )
        unrelated_person = Person.objects.create(
            company=company,
            national_id="8888888888",
            first_name="فرد",
            last_name="نامرتبط",
            birth_date=date(1991, 1, 1),
        )
        specialist = User.objects.create_user(
            username="scoped-people-specialist",
            password="StrongPass!2026",
            role="insurance_specialist",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="تخصیص رشته برای آزمون فهرست اشخاص",
        )
        ServiceRequest.objects.create(
            reference="REQ-SPEC-PEOPLE-001",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=specialist,
            person=visible_person,
            company=company,
            assigned_to=specialist,
            title="رسیدگی مرتبط",
            description="درخواست غیرمحرمانه تخصیص‌یافته",
        )

        client = Client()
        client.force_login(specialist)
        response = client.get(reverse("people_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مرتبط")
        self.assertNotContains(response, "نامرتبط")



class PersonChangeWorkflowTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        from insurance.models import Contract, Insurer, InsuranceLine

        today = timezone.localdate()
        self.company = Company.objects.create(code="PC-A", name="شرکت درخواست تغییر")
        self.insurer = Insurer.objects.create(name="بیمه‌گر درخواست تغییر")
        self.contract = Contract.objects.create(
            code="PC-CONTRACT-1",
            title="قرارداد درمان",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=335),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.contract.companies.add(self.company)

        self.insured = User.objects.create_user(
            username="1234567890",
            password="StrongPass!2026",
            national_id="1234567890",
            mobile="09120000000",
            must_change_password=False,
        )
        self.person = Person.objects.create(
            company=self.company,
            user=self.insured,
            national_id="1234567890",
            first_name="کارمند",
            last_name="آزمایش",
            birth_date=date(1990, 1, 1),
            mobile="09120000000",
            iban="IR000000000000000000000000",
        )
        self.company_rep = User.objects.create_user(
            username="person-change-company-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.insurer_rep = User.objects.create_user(
            username="person-change-insurer-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="person-change-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.insured,
            role=RoleAssignment.Role.INSURED_PERSON,
            line_code="health",
            reason="بیمه‌شده برای آزمون اصلاح اطلاعات",
        )
        RoleAssignment.objects.create(
            user=self.company_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="health",
            reason="نماینده شرکت برای آزمون اصلاح اطلاعات",
        )
        RoleAssignment.objects.create(
            user=self.insurer_rep,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=self.insurer,
            line_code="health",
            reason="نماینده بیمه‌گر برای آزمون اصلاح اطلاعات",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای انتشار گردش‌های پایه",
        )
        call_command("seed_operational_workflows")

    def test_mobile_change_follows_company_insurer_company_and_applies_only_after_final_close(self):
        from django.contrib.contenttypes.models import ContentType
        from organizations.models import PersonChangeRequest
        from accounts.models import UserNotification
        from workflow.models import WorkflowCase
        from workflow.services import transition_case

        client = Client()
        client.force_login(self.insured)
        response = client.post(reverse("person_change_create"), {
            "person": str(self.person.pk),
            "contract": str(self.contract.pk),
            "change_type": PersonChangeRequest.ChangeType.MOBILE,
            "requested_value": "09121112222",
            "reason": "شماره همراه جدید و صحیح جهت اصلاح اطلاعات بیمه‌گر",
        })
        self.assertEqual(response.status_code, 302)
        change = PersonChangeRequest.objects.get(requested_by=self.insured)
        self.person.refresh_from_db()
        self.insured.refresh_from_db()
        self.assertEqual(change.status, PersonChangeRequest.Status.COMPANY_REVIEW)
        self.assertEqual(self.person.mobile, "09120000000")
        self.assertEqual(self.insured.mobile, "09120000000")

        case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(change, for_concrete_model=False),
            object_id=str(change.pk),
        )
        self.assertEqual(case.current_assignee_id, self.company_rep.pk)

        transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer_to_insurer",
            recipient=self.insurer_rep,
            note="مدارک بررسی شد؛ برای اصلاح در سامانه بیمه‌گر ارجاع شد.",
        )
        change.refresh_from_db()
        self.assertEqual(change.status, PersonChangeRequest.Status.INSURER_UPDATE)

        transition_case(
            case_id=case.pk,
            actor=self.insurer_rep,
            action_code="return_to_company",
            recipient=self.company_rep,
            note="اصلاح در سامانه بیمه‌گر انجام شد؛ برای تأیید نهایی بازگشت داده شد.",
        )
        change.refresh_from_db()
        self.assertEqual(change.status, PersonChangeRequest.Status.COMPANY_FINAL_REVIEW)
        self.person.refresh_from_db()
        self.assertEqual(self.person.mobile, "09120000000")

        transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="approve_and_close",
            note="اصلاح انجام‌شده توسط بیمه‌گر بررسی و تأیید شد.",
        )
        change.refresh_from_db()
        self.person.refresh_from_db()
        self.insured.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(change.status, PersonChangeRequest.Status.APPROVED)
        self.assertEqual(change.approved_by_id, self.company_rep.pk)
        self.assertEqual(self.person.mobile, "09121112222")
        self.assertEqual(self.insured.mobile, "09121112222")
        self.assertEqual(case.status, WorkflowCase.Status.CLOSED)
        notification = UserNotification.objects.get(recipient=self.insured)
        self.assertIn("تأیید شد", notification.title)
        self.assertEqual(notification.target_url, reverse("person_change_detail", args=[change.pk]))

    def test_person_change_requests_are_scoped_by_company_and_representative_line(self):
        from organizations.models import PersonChangeRequest

        item = PersonChangeRequest.objects.create(
            person=self.person,
            company=self.company,
            contract=self.contract,
            requested_by=self.insured,
            change_type=PersonChangeRequest.ChangeType.MOBILE,
            current_value=self.person.mobile,
            requested_value="09123334444",
            reason="درخواست آزمایشی برای بررسی دامنه دسترسی",
        )
        client = Client()
        client.force_login(self.company_rep)
        self.assertContains(
            client.get(reverse("person_change_detail", args=[item.pk])),
            "شماره همراه",
        )

        other_line_rep = User.objects.create_user(
            username="person-change-other-line",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=other_line_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="fire",
            reason="نماینده همان شرکت در رشته دیگر",
        )
        client.force_login(other_line_rep)
        response = client.get(reverse("person_change_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 404)

    def test_person_change_request_is_immutable_after_submission(self):
        from django.core.exceptions import ValidationError
        from organizations.models import PersonChangeRequest

        item = PersonChangeRequest.objects.create(
            person=self.person,
            company=self.company,
            contract=self.contract,
            requested_by=self.insured,
            change_type=PersonChangeRequest.ChangeType.MOBILE,
            current_value=self.person.mobile,
            requested_value="09125556666",
            reason="درخواست آزمایشی برای کنترل تغییرناپذیری",
        )
        item.requested_value = "09127778888"
        with self.assertRaises(ValidationError):
            item.save()
