from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import (
    OrganizationalPosition, OrganizationalUnit, PositionAssignment, RoleAssignment,
)
from claims.models import Claim
from insurance.models import Insurer
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
from core.permissions import can_process_request, scoped_requests_for
from .models import (
    BusinessCalendar, WorkflowDefinition, WorkflowEvent, WorkflowStep, WorkflowTransition,
)
from .services import _has_any_role, _scope_for_object, add_business_minutes, resolve_initial_assignee, start_workflow, transition_case
from .presentation import build_workflow_presentation


User = get_user_model()


class WorkflowEngineTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="workflow-admin", password="StrongPass!123", is_superuser=True, is_staff=True
        )
        RoleAssignment.objects.create(
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه آزمون",
        )
        self.department_head = User.objects.create_user(
            username="workflow-department-head",
            password="StrongPass!123",
        )
        RoleAssignment.objects.create(
            user=self.department_head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره آزمون",
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

    def test_confidential_medical_request_summary_never_exposes_free_text_or_description(self):
        from types import SimpleNamespace

        self.request.title = "نام بیماری محرمانه در عنوان آزاد"
        self.request.description = "شرح پزشکی محرمانه و تشخیص"
        self.request.save(update_fields=["title", "description", "updated_at"])
        case = SimpleNamespace(
            content_object=self.request,
            definition=SimpleNamespace(title="گردش کمک‌هزینه درمان"),
            object_id=str(self.request.pk),
            current_assignee_id=self.specialist.pk,
        )

        summary = build_workflow_presentation(case, user=self.specialist)

        self.assertEqual(summary["title"], self.request.get_kind_display())
        self.assertEqual(summary["description"], "")
        self.assertNotIn("نام بیماری محرمانه", summary["title"])
        self.assertTrue(summary["is_confidential"])

    def test_position_only_initial_step_routes_to_active_line_scoped_supervisor(self):
        unit = OrganizationalUnit.objects.create(
            code="WF-POS-UNIT",
            name="واحد رسیدگی درمان",
        )
        position = OrganizationalPosition.objects.create(
            unit=unit,
            code="WF-POS-SUPERVISOR",
            title="سرپرست رسیدگی درمان",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        supervisor = User.objects.create_user(
            username="workflow-position-supervisor",
            password="StrongPass!123",
        )
        PositionAssignment.objects.create(
            user=supervisor,
            unit=unit,
            position=position,
            line_code="health",
            reason="انتصاب سرپرست درمان",
        )
        definition = WorkflowDefinition.objects.create(
            code="test-position-only-initial",
            title="گردش مبتنی بر سمت سازمانی",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="supervisor-review",
            title="بررسی سرپرست درمان",
            order=1,
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            is_initial=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

        assignee = resolve_initial_assignee(
            definition=definition,
            obj=self.request,
        )
        self.assertEqual(assignee.pk, supervisor.pk)

        case = start_workflow(
            obj=self.request,
            code=definition.code,
            actor=self.admin,
            assignee=supervisor,
        )
        self.assertEqual(case.current_step_id, initial.pk)
        self.assertEqual(case.current_assignee_id, supervisor.pk)
        self.assertEqual(case.current_position_assignment_id, PositionAssignment.objects.get(
            user=supervisor, position=position
        ).pk)
        start_event = case.events.get(event_type=WorkflowEvent.EventType.STARTED)
        self.assertEqual(
            start_event.to_position_assignment_id,
            case.current_position_assignment_id,
        )

    def test_position_recipient_routing_respects_ancestor_unit_scope(self):
        root = OrganizationalUnit.objects.create(
            code="WF-ROUTE-ROOT",
            name="ریاست رسیدگی",
        )
        health_unit = OrganizationalUnit.objects.create(
            code="WF-ROUTE-HEALTH",
            name="واحد درمان",
            parent=root,
        )
        unrelated_root = OrganizationalUnit.objects.create(
            code="WF-ROUTE-OTHER-ROOT",
            name="واحد مستقل دیگر",
        )
        supervisor_position = OrganizationalPosition.objects.create(
            unit=root,
            code="WF-ROUTE-SUPERVISOR",
            title="سرپرست بالادست",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        unrelated_position = OrganizationalPosition.objects.create(
            unit=unrelated_root,
            code="WF-ROUTE-OTHER-SUPERVISOR",
            title="سرپرست واحد مستقل",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        PositionAssignment.objects.create(
            user=self.specialist,
            unit=health_unit,
            position=OrganizationalPosition.objects.create(
                unit=health_unit,
                code="WF-ROUTE-HEALTH-SPECIALIST",
                title="کارشناس واحد درمان",
                level=OrganizationalPosition.Level.SPECIALIST,
            ),
            line_code="health",
            reason="جایگاه سازمانی کارشناس مبنای ارجاع",
        )
        supervisor = User.objects.create_user(
            username="workflow-route-supervisor",
            password="StrongPass!123",
        )
        supervisor_assignment = PositionAssignment.objects.create(
            user=supervisor,
            unit=root,
            position=supervisor_position,
            line_code="health",
            reason="سرپرست واحد بالادست درمان",
        )
        unrelated_supervisor = User.objects.create_user(
            username="workflow-route-unrelated-supervisor",
            password="StrongPass!123",
        )
        PositionAssignment.objects.create(
            user=unrelated_supervisor,
            unit=unrelated_root,
            position=unrelated_position,
            line_code="health",
            reason="سرپرست خارج از شاخه سازمانی پرونده",
        )

        definition = WorkflowDefinition.objects.create(
            code="test-position-ancestor-route",
            title="ارجاع سمت‌محور به سرپرست بالادست",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="specialist-review",
            title="بررسی کارشناس",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        supervisor_step = WorkflowStep.objects.create(
            definition=definition,
            code="supervisor-review",
            title="بررسی سرپرست",
            order=2,
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
        )
        final = WorkflowStep.objects.create(
            definition=definition,
            code="head-review",
            title="تصمیم رئیس اداره",
            order=3,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=supervisor_step,
            action_code="refer-to-supervisor",
            title="ارجاع به سرپرست واحد بالادست",
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            recipient_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            position_route_scope=WorkflowTransition.PositionRouteScope.ANCESTORS,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=supervisor_step,
            target_step=final,
            action_code="refer-to-head",
            title="ارجاع برای تصمیم رئیس اداره",
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

        case = start_workflow(
            obj=self.request,
            code=definition.code,
            actor=self.admin,
            assignee=self.specialist,
        )
        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=self.specialist,
                action_code="refer-to-supervisor",
                recipient=unrelated_supervisor,
                note="ارجاع به سرپرست خارج از شاخه",
            )

        case = transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="refer-to-supervisor",
            recipient=supervisor,
            note="ارجاع به سرپرست واحد بالادست",
        )
        self.assertEqual(case.current_step_id, supervisor_step.pk)
        self.assertEqual(case.current_position_assignment_id, supervisor_assignment.pk)
        referral_event = case.events.latest("sent_at")
        self.assertEqual(referral_event.to_position_assignment_id, supervisor_assignment.pk)

        case = transition_case(
            case_id=case.pk,
            actor=supervisor,
            action_code="refer-to-head",
            recipient=self.department_head,
            note="ارسال به رئیس اداره برای تصمیم",
        )
        self.assertEqual(case.current_step_id, final.pk)
        self.assertIsNone(case.current_position_assignment_id)
        final_event = case.events.latest("sent_at")
        self.assertEqual(final_event.from_position_assignment_id, supervisor_assignment.pk)
        self.assertIsNone(final_event.to_position_assignment_id)

    def test_supervisor_can_monitor_subordinate_workflow_but_cannot_act_for_them(self):
        unit_root = OrganizationalUnit.objects.create(
            code="WF-MONITOR-ROOT",
            name="واحد نظارت درمان",
        )
        unit_child = OrganizationalUnit.objects.create(
            code="WF-MONITOR-CHILD",
            name="زیرواحد درمان",
            parent=unit_root,
        )
        supervisor_position = OrganizationalPosition.objects.create(
            unit=unit_root,
            code="WF-MONITOR-SUPERVISOR",
            title="سرپرست درمان",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        specialist_position = OrganizationalPosition.objects.create(
            unit=unit_child,
            code="WF-MONITOR-SPECIALIST",
            title="کارشناس درمان",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        supervisor = User.objects.create_user(
            username="workflow-monitor-supervisor",
            password="StrongPass!123",
        )
        PositionAssignment.objects.create(
            user=supervisor,
            unit=unit_root,
            position=supervisor_position,
            line_code="health",
            reason="سرپرست واحد درمان",
        )
        PositionAssignment.objects.create(
            user=self.specialist,
            unit=unit_child,
            position=specialist_position,
            line_code="health",
            reason="کارشناس زیرمجموعه",
        )
        case = start_workflow(
            obj=self.request,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )

        client = Client()
        client.force_login(supervisor)
        detail = client.get(reverse("workflow_case_detail", args=[case.pk]))

        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.context["can_act"])
        self.assertEqual(detail.context["transitions"], [])
        self.assertContains(detail, "مشاهده تاریخچه")
        self.assertNotContains(detail, 'name="action"')

        denied = client.post(
            reverse("workflow_case_detail", args=[case.pk]),
            {"action": "send-to-head", "note": "اقدام غیرمجاز سرپرست"},
        )
        self.assertEqual(denied.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, self.specialist.pk)
        self.assertEqual(case.current_step_id, self.initial.pk)

    def test_position_grant_expiration_blocks_actions_and_preserves_provenance(self):
        unit = OrganizationalUnit.objects.create(
            code="WF-POS-EXPIRE-UNIT",
            name="واحد انقضای سمت",
        )
        position = OrganizationalPosition.objects.create(
            unit=unit,
            code="WF-POS-EXPIRE",
            title="سرپرست منقضی‌شده",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        supervisor = User.objects.create_user(
            username="workflow-position-expiring",
            password="StrongPass!123",
        )
        assignment = PositionAssignment.objects.create(
            user=supervisor,
            unit=unit,
            position=position,
            line_code="health",
            reason="انتصاب موقت برای آزمون پایان اعتبار",
        )
        definition = WorkflowDefinition.objects.create(
            code="test-position-expiration",
            title="آزمون انقضای انتصاب",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="supervisor-review",
            title="بررسی سرپرست",
            order=1,
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            is_initial=True,
        )
        final = WorkflowStep.objects.create(
            definition=definition,
            code="head-review",
            title="بررسی رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=final,
            action_code="refer-to-head",
            title="ارجاع به رئیس اداره",
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()
        case = start_workflow(
            obj=self.request,
            code=definition.code,
            actor=self.admin,
            assignee=supervisor,
        )
        start_event = case.events.get(event_type=WorkflowEvent.EventType.STARTED)
        self.assertEqual(start_event.to_position_assignment_id, assignment.pk)

        assignment.is_active = False
        assignment.save(update_fields=["is_active"])

        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=supervisor,
                action_code="refer-to-head",
                recipient=self.department_head,
                note="اقدام پس از لغو انتصاب",
            )

        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, supervisor.pk)
        self.assertEqual(case.current_position_assignment_id, assignment.pk)
        self.assertEqual(
            case.events.get(event_type=WorkflowEvent.EventType.STARTED)
            .to_position_assignment_id,
            assignment.pk,
        )

    def test_position_only_workflow_actor_must_hold_active_matching_line_position(self):
        unit = OrganizationalUnit.objects.create(
            code="WF-POS-ACTOR-UNIT",
            name="واحد سرپرستی درمان",
        )
        position = OrganizationalPosition.objects.create(
            unit=unit,
            code="WF-POS-ACTOR",
            title="سرپرست درمان",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        supervisor = User.objects.create_user(
            username="workflow-position-actor",
            password="StrongPass!123",
        )
        PositionAssignment.objects.create(
            user=supervisor,
            unit=unit,
            position=position,
            line_code="health",
            reason="انتصاب سرپرست برای اقدام",
        )
        outsider = User.objects.create_user(
            username="workflow-position-outsider",
            password="StrongPass!123",
        )
        definition = WorkflowDefinition.objects.create(
            code="test-position-only-action",
            title="آزمون مجوز اقدام سمت‌محور",
            created_by=self.admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="supervisor-review",
            title="بررسی سرپرست",
            order=1,
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            is_initial=True,
        )
        final = WorkflowStep.objects.create(
            definition=definition,
            code="head-review",
            title="بررسی رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=final,
            action_code="refer-to-head",
            title="ارجاع به رئیس اداره",
            allowed_roles=[],
            allowed_position_levels=[
                int(OrganizationalPosition.Level.SUPERVISOR)
            ],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

        case = start_workflow(
            obj=self.request,
            code=definition.code,
            actor=self.admin,
            assignee=supervisor,
        )
        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=outsider,
                action_code="refer-to-head",
                recipient=self.department_head,
                note="اقدام با سمت نامعتبر",
            )
        case = transition_case(
            case_id=case.pk,
            actor=supervisor,
            action_code="refer-to-head",
            recipient=self.department_head,
            note="ارجاع توسط سرپرست مجاز",
        )
        self.assertEqual(case.current_assignee_id, self.department_head.pk)

    def test_initial_assignee_prefers_declared_specialist_priority_over_global_roles(self):
        definition = WorkflowDefinition.objects.create(
            code="test-initial-role-priority",
            title="اولویت نقش در تخصیص آغازین",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="initial-review",
            title="رسیدگی تخصصی",
            order=1,
            allowed_roles=[
                RoleAssignment.Role.INSURANCE_SPECIALIST,
                RoleAssignment.Role.DEPARTMENT_HEAD,
                RoleAssignment.Role.SYSTEM_ADMIN,
            ],
            is_initial=True,
        )

        assignee = resolve_initial_assignee(
            definition=definition,
            obj=self.request,
        )

        self.assertEqual(assignee.pk, self.specialist.pk)

    def test_initial_assignee_infers_company_and_line_scope_from_object(self):
        representative = User.objects.create_user(
            username="workflow-scoped-company-rep",
            password="StrongPass!123",
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="health",
            reason="نماینده شرکت برای آزمون تعیین گیرنده",
        )
        definition = WorkflowDefinition.objects.create(
            code="test-object-scope-resolution",
            title="آزمون استخراج محدوده از موضوع گردش کار",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company-review",
            title="بررسی نماینده شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )

        assignee = resolve_initial_assignee(
            definition=definition,
            obj=self.request,
        )

        self.assertEqual(assignee.pk, representative.pk)

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
            recipient=self.department_head,
        )
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, ServiceRequest.Status.COMPLETED)
        self.assertEqual(self.request.assigned_to_id, self.department_head.pk)

        transition_case(
            case_id=case.pk,
            actor=self.department_head,
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
            recipient=self.department_head,
            note="نیازمند تصمیم ریاست",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_step_id, self.final.pk)
        self.assertEqual(case.current_assignee_id, self.department_head.pk)
        self.request.refresh_from_db()
        self.assertEqual(self.request.assigned_to_id, self.department_head.pk)
        self.assertEqual(case.events.count(), 2)
        self.assertIsNotNone(case.first_action_at)

    def test_previous_assignee_can_view_but_cannot_act_after_referral(self):
        case = start_workflow(
            obj=self.request,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="send-to-head",
            recipient=self.department_head,
            note="ارجاع برای تصمیم",
        )

        self.request.refresh_from_db()
        self.assertEqual(self.request.assigned_to_id, self.department_head.pk)
        self.assertIn(self.request, scoped_requests_for(self.specialist))
        self.assertIn(self.request, scoped_requests_for(self.department_head))
        self.assertFalse(can_process_request(self.specialist, self.request))
        self.assertFalse(can_process_request(self.department_head, self.request))

        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=self.specialist,
                action_code="send-to-head",
                recipient=self.department_head,
                note="تلاش برای اقدام پس از انتقال مسئولیت",
            )

    def test_global_manager_cannot_act_on_a_stage_owned_by_another_user(self):
        case = start_workflow(
            obj=self.request,
            code="test-request",
            actor=self.admin,
            assignee=self.specialist,
        )
        with self.assertRaises(PermissionDenied):
            transition_case(
                case_id=case.pk,
                actor=self.admin,
                action_code="send-to-head",
                recipient=self.department_head,
                note="مدیر پرونده را بدون انتساب جاری تغییر داد",
            )

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
                recipient=self.department_head,
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
        with self.assertRaises(ValidationError):
            WorkflowStep.objects.filter(pk=draft_step.pk).update(
                title="تغییر گروهی نامعتبر"
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
        with self.assertRaises(ValidationError):
            WorkflowTransition.objects.filter(pk=draft_transition.pk).update(
                title="تغییر گروهی نامعتبر"
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
