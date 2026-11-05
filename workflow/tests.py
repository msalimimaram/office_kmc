from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import RoleAssignment
from .models import (
    BusinessCalendar, WorkflowDefinition, WorkflowEvent, WorkflowStep, WorkflowTransition,
)
from .services import add_business_minutes, start_workflow, transition_case


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
