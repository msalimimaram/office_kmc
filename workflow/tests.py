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
from .services import _has_any_role, _scope_for_object, add_business_minutes, start_workflow, transition_case


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

    def test_published_workflow_steps_remain_immutable_after_deactivation(self):
        self.definition.is_active = False
        self.definition.save(update_fields=["is_active"])
        self.initial.title = "تغییر غیرمجاز پس از انتشار"
        with self.assertRaises(ValidationError):
            self.initial.save()
        with self.assertRaises(ValidationError):
            self.initial.delete()
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.filter(pk=self.initial.pk).update(title="تغییر گروهی")
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.filter(pk=self.initial.pk).delete()
        with self.assertRaises(ValidationError):
            WorkflowDefinition.objects.filter(pk=self.definition.pk).update(title="تغییر تعریف")
        with self.assertRaises(ValidationError):
            WorkflowDefinition.objects.filter(pk=self.definition.pk).delete()

    def test_workflow_events_reject_queryset_mutation(self):
        case = start_workflow(
            obj=self.specialist,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        event = case.events.first()
        with self.assertRaises(ValidationError):
            WorkflowEvent.objects.filter(pk=event.pk).update(note="tampered")
        with self.assertRaises(ValidationError):
            WorkflowEvent.objects.filter(pk=event.pk).delete()

    def test_step_rejects_unknown_and_unscoped_wildcard_roles(self):
        draft = WorkflowDefinition.objects.create(
            code="draft-invalid-role",
            title="تعریف پیش‌نویس",
            created_by=self.admin,
        )
        for index, roles in enumerate((["made_up_role"], ["*"])):
            with self.subTest(roles=roles):
                with self.assertRaises(ValidationError):
                    WorkflowStep.objects.create(
                        definition=draft,
                        code=f"invalid-role-{index}",
                        title="نقش نامعتبر",
                        order=9 + index,
                        allowed_roles=roles,
                    )

    def test_transition_requires_destination_unless_closing_case(self):
        draft = WorkflowDefinition.objects.create(
            code="draft-invalid-transition",
            title="تعریف پیش‌نویس مسیر",
            created_by=self.admin,
        )
        draft_step = WorkflowStep.objects.create(
            definition=draft,
            code="draft-step",
            title="مرحله پیش‌نویس",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.create(
                definition=draft,
                source_step=draft_step,
                action_code="broken-route",
                title="مسیر ناقص",
                allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            )

    def test_calendar_rejects_invalid_hours_weekdays_and_timezone(self):
        invalid_values = [
            {"start_time": "16:00", "end_time": "08:00"},
            {"working_weekdays": []},
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

    def test_workflow_object_scope_uses_historical_company_snapshot(self):
        company_a = Company.objects.create(code="WF-SCOPE-A", name="شرکت تاریخی الف")
        company_b = Company.objects.create(code="WF-SCOPE-B", name="شرکت تاریخی ب")
        representative = User.objects.create_user(
            username="workflow-snapshot-rep", password="StrongPass!123"
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company_a,
            line_code="health",
            reason="نماینده شرکت الف",
        )
        object_a = type("ClaimScope", (), {
            "company_snapshot_id": company_a.pk,
            "insurer_id": None,
            "line_code": "health",
            "contract": None,
            "person": None,
        })()
        object_b = type("ClaimScope", (), {
            "company_snapshot_id": company_b.pk,
            "insurer_id": None,
            "line_code": "health",
            "contract": None,
            "person": None,
        })()
        self.assertTrue(_has_any_role(
            representative, [RoleAssignment.Role.SUBSIDIARY_REP], **_scope_for_object(object_a)
        ))
        self.assertFalse(_has_any_role(
            representative, [RoleAssignment.Role.SUBSIDIARY_REP], **_scope_for_object(object_b)
        ))

    def test_company_representative_is_denied_when_workflow_object_has_no_company_scope(self):
        representative = User.objects.create_user(
            username="workflow-unscoped-rep", password="StrongPass!123"
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=Company.objects.create(code="WF-UNSCOPED", name="شرکت بدون محدوده"),
            line_code="health",
            reason="نماینده شرکت",
        )
        self.assertFalse(_has_any_role(
            representative,
            [RoleAssignment.Role.SUBSIDIARY_REP],
            line_code="health",
        ))

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
