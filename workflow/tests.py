from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import RoleAssignment
from organizations.models import Company
from .models import (
    BusinessCalendar, WorkflowDefinition, WorkflowEvent, WorkflowStep, WorkflowTransition,
)
from .services import _has_any_role, add_business_minutes, start_workflow, transition_case


User = get_user_model()


class WorkflowEngineTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="workflow-admin", password="StrongPass!123", is_superuser=True, is_staff=True
        )
        self.specialist = User.objects.create_user(
            username="workflow-specialist", password="StrongPass!123"
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="test assignment",
        )
        BusinessCalendar.objects.get_or_create(code="iran-default", defaults={"title": "تقویم پیش‌فرض آزمون", "timezone_name": "Asia/Tehran", "working_weekdays": [5, 6, 0, 1, 2, 3], "start_time": "08:00", "end_time": "16:00"})
        self.definition = WorkflowDefinition.objects.create(
            code="test-request",
            title="گردش کار آزمایشی",
            version=1,
            created_by=self.admin,
        )
        self.initial = WorkflowStep.objects.create(
            definition=self.definition,
            code="specialist",
            title="کارشناس درمان",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
            sla_minutes=60,
        )
        self.final = WorkflowStep.objects.create(
            definition=self.definition,
            code="head",
            title="رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            allow_return=False,
        )
        self.transition = WorkflowTransition.objects.create(
            definition=self.definition,
            source_step=self.initial,
            target_step=self.final,
            action_code="send-to-head",
            title="ارسال به رئیس اداره",
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            requires_note=True,
        )
        self.definition.approved_by = self.admin
        self.definition.is_active = True
        self.definition.save()

    def test_workflow_start_and_routing_record_every_transition(self):
        case = start_workflow(
            obj=self.specialist,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="send-to-head",
            recipient=self.admin,
            note="نیازمند تصمیم ریاست",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_step_id, self.final.pk)
        self.assertEqual(case.current_assignee_id, self.admin.pk)
        self.assertEqual(case.events.count(), 2)
        self.assertIsNotNone(case.first_action_at)

    def test_transition_requires_note_when_configured(self):
        case = start_workflow(
            obj=self.specialist,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        with self.assertRaises(ValidationError):
            transition_case(
                case_id=case.pk,
                actor=self.specialist,
                action_code="send-to-head",
                recipient=self.admin,
                note="",
            )

    def test_sla_uses_configured_working_days_and_hours(self):
        calendar = BusinessCalendar.objects.create(
            code="test-calendar",
            title="تقویم آزمایشی",
            timezone_name="Asia/Tehran",
            working_weekdays=[5, 6],
            start_time="08:00",
            end_time="16:00",
        )
        start = datetime(2026, 11, 7, 15, 30, tzinfo=ZoneInfo("Asia/Tehran"))
        due = add_business_minutes(start, 120, calendar)
        self.assertEqual(due.date().isoformat(), "2026-11-08")
        self.assertEqual((due.hour, due.minute), (9, 30))

    def test_workflow_events_are_append_only(self):
        case = start_workflow(
            obj=self.specialist,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        event = case.events.first()
        event.note = "tampered"
        with self.assertRaises(ValidationError):
            event.save()

    def test_step_rejects_unknown_roles(self):
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.create(
                definition=self.definition,
                code="invalid-role",
                title="نقش نامعتبر",
                order=9,
                allowed_roles=["made_up_role"],
            )

    def test_transition_requires_destination_unless_closing_case(self):
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.create(
                definition=self.definition,
                source_step=self.initial,
                action_code="broken-route",
                title="مسیر ناقص",
                allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            )

    def test_calendar_rejects_invalid_hours_weekdays_and_timezone(self):
        invalid_values = [
            {"start_time": "16:00", "end_time": "08:00"},
            {"working_weekdays": [0, 0, 1]},
            {"working_weekdays": [0, 7]},
            {"timezone_name": "Mars/Olympus"},
        ]
        for index, values in enumerate(invalid_values):
            with self.subTest(values=values):
                with self.assertRaises(ValidationError):
                    BusinessCalendar.objects.create(
                        code=f"invalid-calendar-{index}",
                        title="تقویم نامعتبر",
                        **values,
                    )

    def test_representative_role_is_scoped_to_company_and_insurance_line(self):
        company_a = Company.objects.create(code="WF-A", name="شرکت گردش کار الف")
        company_b = Company.objects.create(code="WF-B", name="شرکت گردش کار ب")
        representative = User.objects.create_user(
            username="workflow-rep", password="StrongPass!123"
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company_a,
            line_code="health",
            reason="test company and line scope",
        )
        roles = [RoleAssignment.Role.SUBSIDIARY_REP]
        self.assertTrue(_has_any_role(
            representative, roles, company_id=company_a.pk, line_code="health"
        ))
        self.assertFalse(_has_any_role(
            representative, roles, company_id=company_b.pk, line_code="health"
        ))
        self.assertFalse(_has_any_role(
            representative, roles, company_id=company_a.pk, line_code="motor"
        ))
