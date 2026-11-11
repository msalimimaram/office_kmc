from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from accounts.models import RoleAssignment
from claims.models import Claim
from insurance.models import Insurer
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
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
        self.company = Company.objects.create(code="WF-TEST", name="شرکت آزمون گردش کار")
        self.request = ServiceRequest.objects.create(
            reference="WF-TEST-REQUEST",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.specialist,
            company=self.company,
            title="درخواست آزمایشی گردش کار",
            description="شرح درخواست آزمایشی",
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

    def test_insurer_representative_cannot_close_a_claim_workflow(self):
        insurer = Insurer.objects.create(name="بیمه‌گر آزمون بستن پرونده")
        insured = Person.objects.create(
            national_id="0012345678",
            first_name="آزمون",
            last_name="بیمه‌شده",
            birth_date="1990-01-01",
        )
        claim = Claim.objects.create(
            claim_number="WF-INSURER-CLOSE-001",
            person=insured,
            insurer=insurer,
            service_type="آزمایش گردش کار",
        )
        insurer_user = User.objects.create_user(
            username="workflow-insurer-rep", password="StrongPass!123"
        )
        RoleAssignment.objects.create(
            user=insurer_user,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=insurer,
            reason="نماینده بیمه‌گر آزمون",
        )
        definition = WorkflowDefinition.objects.create(
            code="insurer-close-test",
            title="گردش کار آزمون منع بستن توسط بیمه‌گر",
            created_by=self.admin,
        )
        step = WorkflowStep.objects.create(
            definition=definition,
            code="insurer-review",
            title="بررسی بیمه‌گر",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURER_REP],
            is_initial=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=step,
            action_code="close-claim",
            title="بستن پرونده",
            allowed_roles=[RoleAssignment.Role.INSURER_REP],
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()
        case = start_workflow(
            obj=claim,
            code="insurer-close-test",
            actor=self.admin,
            assignee=insurer_user,
        )

        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=insurer_user,
                action_code="close-claim",
                note="بستن غیرمجاز توسط بیمه‌گر",
            )

        case.refresh_from_db()
        self.assertEqual(case.status, case.Status.OPEN)
        self.assertEqual(case.current_assignee_id, insurer_user.pk)

    def test_workflow_steps_synchronize_service_request_status_and_final_close(self):
        definition = WorkflowDefinition.objects.create(
            code="request-status-sync",
            title="گردش کار همگام‌سازی وضعیت درخواست",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code=ServiceRequest.Status.IN_REVIEW,
            title="بررسی کارشناس",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        final = WorkflowStep.objects.create(
            definition=definition,
            code=ServiceRequest.Status.COMPLETED,
            title="انجام‌شده",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=final,
            action_code="send-to-head",
            title="ارجاع برای تأیید",
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=final,
            action_code="close-request",
            title="بستن درخواست",
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

        case = start_workflow(
            obj=self.request,
            code="request-status-sync",
            actor=self.admin,
            assignee=self.specialist,
        )
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ServiceRequest.Status.IN_REVIEW)

        case = transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="send-to-head",
            recipient=self.admin,
        )
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ServiceRequest.Status.COMPLETED)

        transition_case(
            case_id=case.pk,
            actor=self.admin,
            action_code="close-request",
        )
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ServiceRequest.Status.CLOSED)

    def test_workflow_start_and_routing_record_every_transition(self):
        case = start_workflow(
            obj=self.request,
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
            obj=self.request,
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
            obj=self.request,
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

    def test_workflow_configuration_rejects_bulk_create_bypass(self):
        with self.assertRaises(ValidationError):
            WorkflowDefinition.objects.bulk_create([
                WorkflowDefinition(code="bulk-definition", title="تعریف گروهی", created_by=self.admin)
            ])
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.bulk_create([
                WorkflowStep(
                    definition=self.definition,
                    code="bulk-step",
                    title="مرحله گروهی",
                    order=9,
                    allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
                )
            ])
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.bulk_create([
                WorkflowTransition(
                    definition=self.definition,
                    source_step=self.initial,
                    target_step=self.final,
                    action_code="bulk-transition",
                    title="مسیر گروهی",
                    allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
                    recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
                )
            ])

    def test_workflow_events_reject_queryset_mutation(self):
        case = start_workflow(
            obj=self.request,
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

    def test_nested_workflow_object_inherits_parent_scope_without_overriding_its_owner(self):
        parent = type("ClaimScope", (), {
            "company_snapshot_id": 741,
            "insurer_id": 852,
            "line_code": "health",
            "contract": None,
            "person": None,
            "submitted_by_id": 963,
            "user_id": None,
        })()
        child = type("ClaimObjectionScope", (), {
            "claim": parent,
            "company_id": None,
            "insurer_id": None,
            "line_code": None,
            "submitted_by_id": 159,
            "user_id": None,
            "person": None,
            "contract": None,
        })()

        scope = _scope_for_object(child)

        self.assertEqual(scope["company_id"], 741)
        self.assertEqual(scope["insurer_id"], 852)
        self.assertEqual(scope["line_code"], "health")
        self.assertEqual(scope["owner_user_id"], 159)

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



    def test_published_workflow_definition_rejects_queryset_and_bulk_mutation(self):
        with self.assertRaises(ValidationError):
            WorkflowDefinition.objects.filter(pk=self.definition.pk).update(published_at=None)

        altered = WorkflowDefinition.objects.get(pk=self.definition.pk)
        altered.title = "عنوان دستکاری‌شده"
        with self.assertRaises(ValidationError):
            WorkflowDefinition.objects.bulk_update([altered], ["title"])

        altered.refresh_from_db()
        altered.published_at = None
        with self.assertRaises(ValidationError):
            altered.save(update_fields=["published_at"])

        altered.refresh_from_db()
        self.assertIsNotNone(altered.published_at)

    def test_publication_timestamp_is_saved_when_activation_uses_update_fields(self):
        draft = WorkflowDefinition.objects.create(
            code="publish-update-fields",
            title="انتشار با update_fields",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=draft,
            code="initial",
            title="مرحله آغازین",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        draft.approved_by = self.admin
        draft.is_active = True
        draft.save(update_fields=["is_active"])

        draft.refresh_from_db()
        self.assertTrue(draft.is_active)
        self.assertIsNotNone(draft.published_at)

    def test_workflow_children_cannot_be_reparented_across_publication_boundary(self):
        draft = WorkflowDefinition.objects.create(
            code="draft-child-parent",
            title="تعریف پیش‌نویس برای آزمون انتقال",
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
        draft_transition = WorkflowTransition.objects.create(
            definition=draft,
            source_step=draft_step,
            action_code="draft-close",
            title="بستن پیش‌نویس",
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            closes_case=True,
        )

        published_step = WorkflowStep.objects.get(pk=self.initial.pk)
        published_step.definition = draft
        with self.assertRaises(ValidationError):
            published_step.save()
        published_step.refresh_from_db()
        published_step.definition = draft
        with self.assertRaises(ValidationError):
            published_step.delete()

        draft_step.definition = self.definition
        with self.assertRaises(ValidationError):
            draft_step.save()
        draft_step.refresh_from_db()
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.filter(pk=draft_step.pk).update(
                definition_id=self.definition.pk
            )
        draft_step.definition = self.definition
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.filter(pk=draft_step.pk).bulk_update(
                [draft_step], ["definition"]
            )

        published_transition = WorkflowTransition.objects.get(pk=self.transition.pk)
        published_transition.definition = draft
        with self.assertRaises(ValidationError):
            published_transition.save()
        published_transition.refresh_from_db()
        published_transition.definition = draft
        with self.assertRaises(ValidationError):
            published_transition.delete()

        draft_transition.definition = self.definition
        with self.assertRaises(ValidationError):
            draft_transition.save()
        draft_transition.refresh_from_db()
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.filter(pk=draft_transition.pk).update(
                definition_id=self.definition.pk
            )
        draft_transition.definition = self.definition
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.filter(pk=draft_transition.pk).bulk_update(
                [draft_transition], ["definition"]
            )


class OperationalWorkflowSeedCommandTests(TestCase):
    def test_seed_command_publishes_all_operational_workflows_idempotently(self):
        from django.core.management import call_command
        from accounts.models import RoleAssignment
        from requests_portal.models import ServiceRequest
        from workflow.models import WorkflowDefinition

        head = User.objects.create_user(
            username="workflow-seed-head",
            password="StrongPass!123",
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای آزمون seed گردش کار",
        )

        call_command("seed_operational_workflows")
        expected = {
            "contract_approval",
            "contract_termination",
            "asset_valuation_approval",
            "asset_policy_approval",
            "asset_endorsement_approval",
            "person_change",
            "claim_review",
            "claim_objection",
        } | set(ServiceRequest.Kind.values)
        active = set(
            WorkflowDefinition.objects.filter(is_active=True).values_list("code", flat=True)
        )
        self.assertTrue(expected.issubset(active))

        # The audit is the publication gate: all request kinds and domain
        # workflows must have valid status mappings, roles, and transitions.
        call_command("audit_workflows")

        versions_before = dict(
            WorkflowDefinition.objects.filter(code__in=expected).values_list("code", "version")
        )
        call_command("seed_operational_workflows")
        versions_after = dict(
            WorkflowDefinition.objects.filter(code__in=expected).values_list("code", "version")
        )
        self.assertEqual(versions_before, versions_after)
        self.assertEqual(
            WorkflowDefinition.objects.filter(code__in=expected, is_active=True).count(),
            len(expected),
        )
