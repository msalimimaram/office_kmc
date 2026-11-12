from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import (
    OrganizationalPosition, OrganizationalUnit, PositionAssignment,
    RoleAssignment, User,
)
from reports.models import Report, ReportVersion
from workflow.models import WorkflowCase
from workflow.services import transition_case


class ManagementReportWorkflowTests(TestCase):
    def setUp(self):
        self.unit = OrganizationalUnit.objects.create(
            code="REPORT-UNIT", name="واحد تهیه گزارش"
        )
        self.specialist = User.objects.create_user(
            username="report-specialist", password="StrongPass!2026",
            must_change_password=False,
        )
        self.supervisor = User.objects.create_user(
            username="report-supervisor", password="StrongPass!2026",
            must_change_password=False,
        )
        self.responsible = User.objects.create_user(
            username="report-responsible", password="StrongPass!2026",
            must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="report-department-head", password="StrongPass!2026",
            must_change_password=False,
        )
        self.specialist_position = OrganizationalPosition.objects.create(
            unit=self.unit, code="REPORT-SPECIALIST", title="کارشناس گزارش",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        self.supervisor_position = OrganizationalPosition.objects.create(
            unit=self.unit, code="REPORT-SUPERVISOR", title="سرپرست گزارش",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        self.responsible_position = OrganizationalPosition.objects.create(
            unit=self.unit, code="REPORT-RESPONSIBLE", title="مسئول گزارش",
            level=OrganizationalPosition.Level.RESPONSIBLE,
        )
        PositionAssignment.objects.create(
            user=self.specialist, unit=self.unit, position=self.specialist_position,
            line_code="health", reason="سمت تهیه‌کننده گزارش",
        )
        PositionAssignment.objects.create(
            user=self.supervisor, unit=self.unit, position=self.supervisor_position,
            line_code="health", reason="سمت بررسی سرپرست گزارش",
        )
        PositionAssignment.objects.create(
            user=self.responsible, unit=self.unit, position=self.responsible_position,
            line_code="health", reason="سمت بررسی مسئول گزارش",
        )
        RoleAssignment.objects.create(
            user=self.specialist, role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health", reason="نقش کارشناس تهیه گزارش",
        )
        RoleAssignment.objects.create(
            user=self.head, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای گردش گزارش",
        )
        call_command("seed_operational_workflows")

    def _create_report(self):
        client = Client()
        client.force_login(self.specialist)
        response = client.post(reverse("report_create"), {
            "title": "گزارش عملکرد درمان تکمیلی",
            "report_type": Report.Type.OPERATIONS,
            "line_code": "health",
            "company": "",
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "summary": "خلاصه مدیریتی گزارش عملکرد درمان تکمیلی",
            "body": "این متن گزارش برای بررسی سلسله‌مراتبی و ثبت نسخه‌های متوالی تهیه شده است.",
        })
        self.assertEqual(response.status_code, 302)
        report = Report.objects.get(title="گزارش عملکرد درمان تکمیلی")
        case = WorkflowCase.objects.get(
            content_type__app_label="reports",
            content_type__model="report",
            object_id=str(report.pk),
        )
        self.assertEqual(case.current_assignee_id, self.supervisor.pk)
        self.assertEqual(report.status, Report.Status.SUPERVISOR_REVIEW)
        self.assertEqual(report.versions.count(), 1)
        return report, case

    def test_report_follows_supervisor_responsible_head_and_final_closure(self):
        report, case = self._create_report()
        transition_case(
            case_id=case.pk, actor=self.supervisor,
            action_code="approve_to_responsible", recipient=self.responsible,
            note="تأیید سرپرست",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, self.responsible.pk)
        self.assertEqual(report.__class__.objects.get(pk=report.pk).status, Report.Status.RESPONSIBLE_REVIEW)

        transition_case(
            case_id=case.pk, actor=self.responsible,
            action_code="approve_to_head", recipient=self.head,
            note="تأیید مسئول",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, self.head.pk)

        transition_case(
            case_id=case.pk, actor=self.head,
            action_code="approve", recipient=self.head,
            note="تأیید نهایی",
        )
        case.refresh_from_db()
        self.assertEqual(report.__class__.objects.get(pk=report.pk).status, Report.Status.APPROVED)

        transition_case(
            case_id=case.pk, actor=self.head,
            action_code="finalize", note="مختومه‌سازی",
        )
        case.refresh_from_db()
        report.refresh_from_db()
        self.assertEqual(case.status, WorkflowCase.Status.CLOSED)
        self.assertEqual(report.status, Report.Status.CLOSED)

    def test_return_to_original_author_and_versioned_resubmission(self):
        report, case = self._create_report()
        transition_case(
            case_id=case.pk, actor=self.supervisor,
            action_code="return_to_creator", recipient=self.specialist,
            note="اصلاح مبنای محاسبه و افزودن توضیحات",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, self.specialist.pk)
        self.assertEqual(report.__class__.objects.get(pk=report.pk).status, Report.Status.RETURNED)

        client = Client()
        client.force_login(self.specialist)
        response = client.post(reverse("report_detail", args=[report.pk]), {
            "summary": "خلاصه اصلاح‌شده گزارش عملکرد درمان تکمیلی",
            "body": "متن نسخه دوم گزارش با اصلاح مبنای محاسبه و توضیحات تکمیلی برای بررسی مجدد.",
        })
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        case.refresh_from_db()
        self.assertEqual(report.versions.count(), 2)
        self.assertEqual(case.current_assignee_id, self.supervisor.pk)
        self.assertEqual(report.status, Report.Status.SUPERVISOR_REVIEW)

    def test_report_status_cannot_be_changed_outside_workflow(self):
        report, case = self._create_report()
        report.status = Report.Status.APPROVED
        with self.assertRaises(ValidationError):
            report.save()
        report.refresh_from_db()
        self.assertEqual(report.status, Report.Status.SUPERVISOR_REVIEW)

    def test_unrelated_company_user_cannot_open_report(self):
        report, case = self._create_report()
        unrelated = User.objects.create_user(
            username="report-unrelated", password="StrongPass!2026",
            must_change_password=False,
        )
        client = Client()
        client.force_login(unrelated)
        self.assertEqual(client.get(reverse("report_detail", args=[report.pk])).status_code, 404)
