from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask



class WorkflowDashboardQueueTests(TestCase):
    def setUp(self):
        from accounts.models import OrganizationalPosition, OrganizationalUnit
        from django.contrib.contenttypes.models import ContentType
        from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowStep
        from workflow.services import start_workflow

        self.company = Company.objects.create(
            code="DASH-WF-COMPANY",
            name="شرکت صف گردش‌کار",
        )
        self.submitter = User.objects.create_user(
            username="dash-wf-submitter",
            password="StrongPass!2026",
            role="employee",
            company=self.company,
            must_change_password=False,
        )
        self.specialist = User.objects.create_user(
            username="dash-wf-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.other_specialist = User.objects.create_user(
            username="dash-wf-other-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="dash-wf-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس صف داشبورد",
        )
        RoleAssignment.objects.create(
            user=self.other_specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس دیگر",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای انتشار گردش",
        )

        self.own_request = ServiceRequest.objects.create(
            reference="IB-DASH-WF-OWN",
            kind=ServiceRequest.Kind.ADD_COVERAGE,
            submitted_by=self.submitter,
            company=self.company,
            title="افزایش پوشش درمانی خودم",
            description="درخواست قابل رسیدگی",
        )
        self.other_request = ServiceRequest.objects.create(
            reference="IB-DASH-WF-OTHER",
            kind=ServiceRequest.Kind.ADD_COVERAGE,
            submitted_by=self.submitter,
            company=self.company,
            title="افزایش پوشش اختصاص‌یافته به همکار",
            description="این پرونده نباید در صف من باشد",
        )

        definition = WorkflowDefinition.objects.create(
            code="dashboard-workflow-queue",
            title="گردش صف داشبورد",
            created_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="under_review",
            title="بررسی کارشناس",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        definition.approved_by = self.head
        definition.is_active = True
        definition.save()

        self.own_case = start_workflow(
            obj=self.own_request,
            code=definition.code,
            actor=self.head,
            assignee=self.specialist,
        )
        self.other_case = start_workflow(
            obj=self.other_request,
            code=definition.code,
            actor=self.head,
            assignee=self.other_specialist,
        )

    def test_specialist_dashboard_shows_only_currently_assigned_workflow_cases(self):
        client = Client()
        client.force_login(self.specialist)
        response = client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["workflow_action_count"], 1)
        self.assertEqual(
            [case.pk for case in response.context["workflow_action_cases"]],
            [self.own_case.pk],
        )
        self.assertContains(response, "افزایش پوشش درمانی خودم")
        self.assertNotContains(response, "افزایش پوشش اختصاص‌یافته به همکار")

    def test_department_head_has_read_only_oversight_counts_separate_from_personal_queue(self):
        client = Client()
        client.force_login(self.head)
        response = client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["workflow_action_count"], 0)
        self.assertEqual(response.context["oversight_workflow_count"], 2)
        self.assertContains(response, "نمای نظارتی")
        self.assertContains(response, "پرونده‌های باز و در انتظار")


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
