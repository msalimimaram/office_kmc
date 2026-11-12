from django.contrib import admin
from django.test import RequestFactory
from datetime import date, timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from accounts.models import RoleAssignment, User
from organizations.models import Company, CompanyLeadershipPosition, CompanyLeadershipTitle, Person, PersonEmployment, PersonChangeRequest
from insurance.models import Contract, Insurer, InsuranceLine
from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowStep, WorkflowTransition
from workflow.services import transition_case
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

    def test_former_company_representative_cannot_view_transferred_employee_profile(self):
        from datetime import timedelta
        from django.utils import timezone

        today = timezone.localdate()
        old_company = Company.objects.create(code="HIST-A", name="شرکت سابق")
        current_company = Company.objects.create(code="HIST-B", name="شرکت جاری")
        person = Person.objects.create(
            company=old_company,
            national_id="1122334455",
            first_name="کارمند",
            last_name="انتقال‌یافته",
            birth_date=date(1990, 1, 1),
        )
        PersonEmployment.objects.create(
            person=person,
            company=old_company,
            valid_from=today - timedelta(days=365),
            valid_until=today - timedelta(days=1),
            status=PersonEmployment.Status.TRANSFERRED,
        )
        PersonEmployment.objects.create(
            person=person,
            company=current_company,
            valid_from=today,
            status=PersonEmployment.Status.ACTIVE,
        )
        old_rep = User.objects.create_user(
            username="historical-company-rep",
            password="StrongPass!2026",
            must_change_password=False,
            company=old_company,
        )
        current_rep = User.objects.create_user(
            username="current-company-rep",
            password="StrongPass!2026",
            must_change_password=False,
            company=current_company,
        )
        RoleAssignment.objects.create(
            user=old_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=old_company,
            line_code="*",
            reason="نماینده شرکت سابق",
        )
        RoleAssignment.objects.create(
            user=current_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=current_company,
            line_code="*",
            reason="نماینده شرکت جاری",
        )

        client = Client()
        client.force_login(old_rep)
        old_response = client.get(reverse("people_list"))
        self.assertNotContains(old_response, "انتقال‌یافته")

        client.force_login(current_rep)
        current_response = client.get(reverse("people_list"))
        self.assertContains(current_response, "انتقال‌یافته")

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
            must_change_password=False, company=self.company_a,
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
            title="مدیرعامل شرکت ب",
            valid_from=date(2025, 1, 1),
            declared_by=self.head,
        )

    def test_company_representative_can_declare_title_for_own_company_and_title_appears_in_people_list(self):
        client = Client()
        client.force_login(self.rep)
        response = client.post(reverse("company_leadership_titles"), {
            "company": str(self.company_a.pk),
            "person": str(self.person_a.pk),
            "position": str(CompanyLeadershipPosition.objects.get(company=self.company_a, code="assistant_ceo").pk),
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
        self.assertNotContains(people, "مدیرعامل شرکت ب")


    def test_company_representative_does_not_see_another_company_title_for_a_visible_person(self):
        PersonEmployment.objects.create(
            person=self.person_a,
            company=self.company_b,
            valid_from=date(2025, 1, 1),
            status=PersonEmployment.Status.ACTIVE,
        )
        CompanyLeadershipTitle.objects.create(
            company=self.company_b,
            person=self.person_a,
            title="عضو هیئت‌مدیره محرمانه شرکت ب",
            valid_from=date(2025, 1, 1),
            declared_by=self.head,
        )

        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("people_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.person_a.first_name)
        self.assertNotContains(response, "عضو هیئت‌مدیره محرمانه شرکت ب")

    def test_company_representative_cannot_forge_another_company_in_post(self):
        client = Client()
        client.force_login(self.rep)
        response = client.post(reverse("company_leadership_titles"), {
            "company": str(self.company_b.pk),
            "person": str(self.person_b.pk),
            "position": str(CompanyLeadershipPosition.objects.get(company=self.company_b, code="ceo").pk),
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
        self.assertNotContains(response, "مدیرعامل شرکت ب")

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
            must_change_password=False, company=self.company,
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
        notification = UserNotification.objects.get(
            recipient=self.insured,
            target_url=reverse("person_change_detail", args=[change.pk]),
            title="درخواست اصلاح اطلاعات تأیید شد",
        )
        self.assertIn("تأیید شد", notification.title)

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
            must_change_password=False, company=self.company,
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

class PersonChangeRequestWorkflowTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.company = Company.objects.create(code="PCR-COMP", name="شرکت درخواست تغییر")
        self.insurer = Insurer.objects.create(name="بیمه‌گر درخواست تغییر")
        self.admin = User.objects.create_superuser(
            username="pcr-admin",
            email="pcr-admin@example.invalid",
            password="StrongPass!2026",
        )
        self.insured = User.objects.create_user(
            username="1234567890",
            national_id="1234567890",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.person = Person.objects.create(
            company=self.company,
            user=self.insured,
            national_id="1234567890",
            first_name="کارمند",
            last_name="درخواست‌کننده",
            birth_date=date(1990, 1, 1),
            mobile="09120000000",
            iban="IR120000000000000000000000",
        )
        PersonEmployment.objects.create(
            person=self.person,
            company=self.company,
            personnel_code="PCR-001",
            valid_from=self.today - timedelta(days=300),
            status=PersonEmployment.Status.ACTIVE,
        )
        self.contract = Contract.objects.create(
            code="PCR-CONTRACT",
            title="قرارداد درمان درخواست تغییر",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=365),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.contract.companies.add(self.company)

        self.company_rep = User.objects.create_user(
            username="pcr-company-rep",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
        )
        self.insurer_rep = User.objects.create_user(
            username="pcr-insurer-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.other_company_rep = User.objects.create_user(
            username="pcr-other-company-rep",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
        )
        RoleAssignment.objects.create(
            user=self.insured,
            role=RoleAssignment.Role.INSURED_PERSON,
            valid_from=self.today,
            reason="بیمه‌شده اصلی",
        )
        for user in (self.company_rep, self.other_company_rep):
            RoleAssignment.objects.create(
                user=user,
                role=RoleAssignment.Role.SUBSIDIARY_REP,
                company=self.company,
                line_code=InsuranceLine.HEALTH,
                valid_from=self.today,
                reason="نماینده شرکت برای درخواست اصلاح",
            )
        RoleAssignment.objects.create(
            user=self.insurer_rep,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=self.insurer,
            valid_from=self.today,
            reason="نماینده بیمه‌گر برای اصلاح اطلاعات",
        )
        self._create_workflow()
        self.client = Client()

    def _create_workflow(self):
        definition = WorkflowDefinition.objects.create(
            code="person_change",
            title="گردش اصلاح اطلاعات بیمه‌شده",
            created_by=self.admin,
        )
        roles = {
            "company": [RoleAssignment.Role.SUBSIDIARY_REP],
            "insurer_representative": [RoleAssignment.Role.INSURER_REP],
        }
        steps = {}
        for order, (code, title, allowed_roles) in enumerate([
            (PersonChangeRequest.Status.COMPANY_REVIEW, "بررسی نماینده شرکت", roles["company"]),
            (PersonChangeRequest.Status.INSURER_UPDATE, "اقدام بیمه‌گر", roles["insurer_representative"]),
            (PersonChangeRequest.Status.COMPANY_FINAL_REVIEW, "بازبینی نهایی شرکت", roles["company"]),
            (PersonChangeRequest.Status.APPROVED, "تأیید نهایی", roles["company"]),
            (PersonChangeRequest.Status.REJECTED, "رد نهایی", roles["company"]),
        ], start=1):
            steps[code] = WorkflowStep.objects.create(
                definition=definition,
                code=code,
                title=title,
                order=order,
                allowed_roles=allowed_roles,
                is_initial=(code == PersonChangeRequest.Status.COMPANY_REVIEW),
            )

        transitions = [
            (
                PersonChangeRequest.Status.COMPANY_REVIEW,
                PersonChangeRequest.Status.INSURER_UPDATE,
                "refer-to-insurer",
                roles["company"],
                roles["insurer_representative"],
                False,
            ),
            (
                PersonChangeRequest.Status.INSURER_UPDATE,
                PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                "return-to-company",
                roles["insurer_representative"],
                roles["company"],
                False,
            ),
            (
                PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                PersonChangeRequest.Status.APPROVED,
                "approve-person-change",
                roles["company"],
                roles["company"],
                False,
            ),
            (
                PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                PersonChangeRequest.Status.REJECTED,
                "reject-person-change",
                roles["company"],
                roles["company"],
                False,
            ),
            (
                PersonChangeRequest.Status.APPROVED,
                None,
                "close-approved",
                roles["company"],
                [],
                True,
            ),
            (
                PersonChangeRequest.Status.REJECTED,
                None,
                "close-rejected",
                roles["company"],
                [],
                True,
            ),
            (
                PersonChangeRequest.Status.COMPANY_REVIEW,
                None,
                "premature-close",
                roles["company"],
                [],
                True,
            ),
            (
                PersonChangeRequest.Status.INSURER_UPDATE,
                None,
                "insurer-close",
                roles["insurer_representative"],
                [],
                True,
            ),
        ]
        for source, target, action, allowed, recipients, closes in transitions:
            WorkflowTransition.objects.create(
                definition=definition,
                source_step=steps[source],
                target_step=steps[target] if target else None,
                action_code=action,
                title=action,
                allowed_roles=allowed,
                recipient_roles=recipients,
                closes_case=closes,
            )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

    def _create_request(self, *, change_type=PersonChangeRequest.ChangeType.MOBILE, requested_value="09121111111", expected_assignee=None):
        self.client.force_login(self.insured)
        response = self.client.post(
            reverse("person_change_create"),
            {
                "person": str(self.person.pk),
                "contract": str(self.contract.pk),
                "change_type": change_type,
                "requested_value": requested_value,
                "reason": "اطلاعات ثبت‌شده نیازمند اصلاح و تطبیق با مدرک معتبر است.",
            },
        )
        self.assertEqual(response.status_code, 302)
        item = PersonChangeRequest.objects.get(person=self.person, change_type=change_type)
        content_type = ContentType.objects.get_for_model(PersonChangeRequest, for_concrete_model=False)
        case = WorkflowCase.objects.get(content_type=content_type, object_id=str(item.pk))
        self.assertEqual(case.current_assignee_id, (expected_assignee or self.company_rep).pk)
        return item, case

    def test_insured_person_receives_notice_after_company_rep_refers_their_change(self):
        from accounts.models import UserNotification

        item, case = self._create_request()
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer-to-insurer",
            recipient=self.insurer_rep,
            note="بررسی اولیه انجام و برای اقدام بیمه‌گر ارسال شد.",
        )

        notice = UserNotification.objects.get(
            recipient=self.insured,
            target_url=reverse("person_change_detail", args=[item.pk]),
            title="وضعیت درخواست شما به‌روزرسانی شد",
        )
        self.assertEqual(notice.actor_id, self.company_rep.pk)
        self.assertEqual(case.current_assignee_id, self.insurer_rep.pk)

        self.client.force_login(self.insured)
        detail = self.client.get(reverse("person_change_detail", args=[item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "09121111111")

    def test_insured_user_who_is_also_only_company_rep_can_receive_own_request(self):
        RoleAssignment.objects.filter(
            user__in=[self.company_rep, self.other_company_rep],
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
        ).update(is_active=False)
        RoleAssignment.objects.create(
            user=self.insured,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code=InsuranceLine.HEALTH,
            valid_from=self.today,
            reason="بیمه‌شده و تنها نماینده شرکت",
        )
        item, case = self._create_request(expected_assignee=self.insured)
        self.assertEqual(item.requested_by_id, self.insured.pk)
        self.assertEqual(case.current_assignee_id, self.insured.pk)

    def test_mobile_change_applies_only_after_company_insurer_company_review(self):
        item, case = self._create_request()
        self.assertEqual(item.status, PersonChangeRequest.Status.COMPANY_REVIEW)

        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer-to-insurer",
            recipient=self.insurer_rep,
        )
        item.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.INSURER_UPDATE)

        case = transition_case(
            case_id=case.pk,
            actor=self.insurer_rep,
            action_code="return-to-company",
            recipient=self.company_rep,
        )
        item.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.COMPANY_FINAL_REVIEW)

        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="approve-person-change",
            recipient=self.company_rep,
        )
        self.person.refresh_from_db()
        self.assertEqual(self.person.mobile, "09120000000")

        transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="close-approved",
        )
        item.refresh_from_db()
        self.person.refresh_from_db()
        self.insured.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.APPROVED)
        self.assertEqual(self.person.mobile, "09121111111")
        self.assertEqual(self.insured.mobile, "09121111111")
        self.assertEqual(item.approved_by_id, self.company_rep.pk)

    def test_company_rep_cannot_close_before_final_review(self):
        item, case = self._create_request()
        with self.assertRaises(ValidationError):
            transition_case(
                case_id=case.pk,
                actor=self.company_rep,
                action_code="premature-close",
            )
        item.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.COMPANY_REVIEW)
        self.assertEqual(case.status, WorkflowCase.Status.OPEN)

    def test_insurer_rep_cannot_close_applicant_side_person_change_request(self):
        item, case = self._create_request()
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer-to-insurer",
            recipient=self.insurer_rep,
        )
        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=self.insurer_rep,
                action_code="insurer-close",
            )
        item.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.INSURER_UPDATE)
        self.assertEqual(case.status, WorkflowCase.Status.WAITING)

    def test_person_change_status_and_history_cannot_be_mutated_outside_workflow(self):
        item, _case = self._create_request()
        item.status = PersonChangeRequest.Status.APPROVED
        with self.assertRaises(ValidationError):
            item.save()
        with self.assertRaises(ValidationError):
            PersonChangeRequest.objects.filter(pk=item.pk).update(
                status=PersonChangeRequest.Status.APPROVED
            )
        with self.assertRaises(ValidationError):
            item.delete()

    def test_non_assigned_company_rep_sees_masked_personal_values(self):
        item, _case = self._create_request()
        self.client.force_login(self.other_company_rep)
        response = self.client.get(reverse("person_change_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "091••••00")
        self.assertContains(response, "091••••11")
        self.assertNotContains(response, "09121111111")
        self.assertNotContains(response, "اطلاعات ثبت‌شده نیازمند اصلاح و تطبیق با مدرک معتبر است.")

    def test_rejection_does_not_change_person_data(self):
        item, case = self._create_request()
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer-to-insurer",
            recipient=self.insurer_rep,
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.insurer_rep,
            action_code="return-to-company",
            recipient=self.company_rep,
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="reject-person-change",
            recipient=self.company_rep,
        )
        transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="close-rejected",
        )
        item.refresh_from_db()
        self.person.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.REJECTED)
        self.assertEqual(self.person.mobile, "09120000000")

    def test_national_id_approval_updates_person_and_username_together(self):
        item, case = self._create_request(
            change_type=PersonChangeRequest.ChangeType.NATIONAL_ID,
            requested_value="1234567891",
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="refer-to-insurer",
            recipient=self.insurer_rep,
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.insurer_rep,
            action_code="return-to-company",
            recipient=self.company_rep,
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="approve-person-change",
            recipient=self.company_rep,
        )
        transition_case(
            case_id=case.pk,
            actor=self.company_rep,
            action_code="close-approved",
        )
        item.refresh_from_db()
        self.person.refresh_from_db()
        self.insured.refresh_from_db()
        self.assertEqual(item.status, PersonChangeRequest.Status.APPROVED)
        self.assertEqual(self.person.national_id, "1234567891")
        self.assertEqual(self.insured.national_id, "1234567891")
        self.assertEqual(self.insured.username, "1234567891")


class CompanyAdminAuthorizationTests(TestCase):
    def test_company_master_data_is_system_admin_only(self):
        company_admin = admin.site._registry[Company]
        factory = RequestFactory()
        head = User.objects.create_user(
            username="company-admin-head", password="StrongPass!2026",
            is_staff=True, must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=head, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای آزمون مرز مدیریت شرکت",
        )
        sysadmin = User.objects.create_user(
            username="company-admin-sys", password="StrongPass!2026",
            is_staff=True, must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=sysadmin, role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه برای آزمون مرز مدیریت شرکت",
        )
        head_request = factory.get("/admin/")
        head_request.user = head
        admin_request = factory.get("/admin/")
        admin_request.user = sysadmin
        self.assertFalse(company_admin.has_module_permission(head_request))
        self.assertFalse(company_admin.has_add_permission(head_request))
        self.assertTrue(company_admin.has_module_permission(admin_request))
        self.assertTrue(company_admin.has_add_permission(admin_request))
        self.assertFalse(company_admin.has_delete_permission(admin_request))
