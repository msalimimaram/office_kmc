from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="DASH-A", name="شرکت داشبورد")
        self.employee = User.objects.create_user(
            username="dashboard-employee", password="StrongPass!2026",
            must_change_password=False, role="employee", company=self.company,
        )
        self.other_employee = User.objects.create_user(
            username="dashboard-other", password="StrongPass!2026",
            must_change_password=False, role="employee", company=self.company,
        )

    def test_employee_dashboard_shows_personal_modules_not_management_modules(self):
        client = Client()
        client.force_login(self.employee)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "پنل بیمه‌شده")
        self.assertContains(response, "درخواست‌های من")
        self.assertNotContains(response, "دارایی‌های بیمه‌شده")
        self.assertNotContains(response, "قراردادهای بیمه")
        self.assertNotContains(response, "ورود اطلاعات از اکسل")

    def test_employee_dashboard_does_not_show_another_users_request(self):
        ServiceRequest.objects.create(
            reference="IB-DASH-OWN", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.employee, company=self.company,
            title="درخواست شخصی قابل مشاهده", description="شرح",
        )
        ServiceRequest.objects.create(
            reference="IB-DASH-OTHER", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.other_employee, company=self.company,
            title="درخواست محرمانه برای کاربر دیگر", description="شرح",
        )
        client = Client()
        client.force_login(self.employee)
        response = client.get(reverse("dashboard"))
        self.assertContains(response, "درخواست شخصی قابل مشاهده")
        self.assertNotContains(response, "درخواست محرمانه برای کاربر دیگر")

    def test_department_head_dashboard_includes_review_queue(self):
        head = User.objects.create_user(
            username="dashboard-head", password="StrongPass!2026",
            must_change_password=False, role="department_head",
        )
        ServiceRequest.objects.create(
            reference="IB-DASH-MED", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.employee, company=self.company,
            title="درخواست محرمانه کمک‌هزینه", description="شرح محرمانه",
            is_confidential=True,
        )
        client = Client()
        client.force_login(head)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "درخواست محرمانه کمک‌هزینه")
        self.assertContains(response, "ورود اطلاعات از اکسل")

    def test_specialist_dashboard_does_not_count_confidential_request_tasks(self):
        specialist = User.objects.create_user(
            username="dashboard-specialist", password="StrongPass!2026",
            must_change_password=False, role="insurance_specialist",
        )
        head = User.objects.create_user(
            username="dashboard-task-head", password="StrongPass!2026",
            must_change_password=False, role="department_head",
        )
        RoleAssignment.objects.create(
            user=specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
        )
        confidential_request = ServiceRequest.objects.create(
            reference="IB-DASH-SECRET-TASK",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.employee,
            company=self.company,
            title="درخواست پزشکی",
            description="شرح محرمانه",
            is_confidential=True,
        )
        task = InternalTask.objects.create(
            title="وظیفه مرتبط با پرونده محرمانه",
            description="شرح",
            created_by=head,
            related_request=confidential_request,
        )
        task.assignees.add(specialist)

        client = Client()
        client.force_login(specialist)
        response = client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["task_count"], 0)
