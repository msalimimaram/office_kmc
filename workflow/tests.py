from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse

from accounts.models import (
    OrganizationalPosition, OrganizationalUnit, PositionAssignment, RoleAssignment,
)
from claims.models import Claim
from insurance.models import Contract, Insurer, InsuranceLine
from organizations.models import Company, Person, PersonChangeRequest
from requests_portal.models import ServiceRequest
from core.permissions import can_process_request, scoped_requests_for
from .models import (
    BusinessCalendar, WorkflowCase, WorkflowDefinition, WorkflowEvent, WorkflowStep, WorkflowTransition,
)
from .services import _has_any_role, _scope_for_object, add_business_minutes, resolve_initial_assignee, start_workflow, transition_case, set_final_lock, unlock_final_lock
from .presentation import build_workflow_presentation


User = get_user_model()


class WorkflowEngineTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="workflow-admin", password="StrongPass!123", is_superuser=True,
            is_staff=True, must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه آزمون",
        )
        self.department_head = User.objects.create_user(
            username="workflow-department-head",
            password="StrongPass!123",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.department_head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره آزمون",
        )
        self.specialist = User.objects.create_user(
            username="workflow-specialist", password="StrongPass!123",
            must_change_password=False,
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

    def test_former_person_change_assignee_cannot_read_sensitive_workflow_notes(self):
        from datetime import date, timedelta
        from django.test import Client
        from django.urls import reverse

        today = timezone.localdate()
        insurer = Insurer.objects.create(name="بیمه‌گر آزمون تغییر شخص")
        contract = Contract.objects.create(
            code="PERSON-CHANGE-WF-CONTRACT", title="قرارداد تغییر شخص",
            insurer=insurer, line=InsuranceLine.HEALTH,
            start_date=today - timedelta(days=30), end_date=today + timedelta(days=300),
            status=Contract.Status.ACTIVE, is_active=True,
        )
        contract.companies.add(self.company)
        person = Person.objects.create(
            company=self.company, user=self.specialist, national_id="1234567890",
            first_name="کاربر", last_name="آزمایش", birth_date=date(1990, 1, 1),
            mobile="09120000000",
        )
        change = PersonChangeRequest.objects.create(
            person=person, company=self.company, contract=contract,
            requested_by=self.specialist,
            change_type=PersonChangeRequest.ChangeType.MOBILE,
            current_value="09120000000", requested_value="09121111111",
            reason="اصلاح شماره همراه به درخواست بیمه‌شده",
        )
        representative = User.objects.create_user(
            username="person-change-current-rep", password="StrongPass!123",
            must_change_password=False, company=self.company,
        )
        from accounts.models import RoleAssignment
        RoleAssignment.objects.create(
            user=representative, role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company, line_code="health",
            reason="نماینده جاری پرونده تغییر اطلاعات",
        )
        definition = WorkflowDefinition.objects.create(
            code="person_change", title="گردش اصلاح اطلاعات", version=91,
            created_by=self.admin, approved_by=self.admin,
        )
        step = WorkflowStep.objects.create(
            definition=definition, code="company_final_review",
            title="بازبینی نماینده شرکت", order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP], is_initial=True,
        )
        definition.is_active = True
        definition.save()
        case = WorkflowCase.objects.create(
            definition=definition,
            content_type=ContentType.objects.get_for_model(change, for_concrete_model=False),
            object_id=str(change.pk), current_step=step, current_assignee=representative,
        )
        WorkflowEvent.objects.create(
            workflow_case=case, actor=self.specialist,
            event_type=WorkflowEvent.EventType.REFERRED,
            from_assignee=self.specialist, to_assignee=representative,
            to_step=step,
            note="شماره قبلی 09120000000 و شماره جدید 09121111111",
        )

        client = Client()
        client.force_login(self.specialist)
        response = client.get(reverse("workflow_case_detail", args=[case.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "09120000000")
        self.assertNotContains(response, "09121111111")

    def test_workflow_initiator_can_read_routing_history_but_not_internal_notes_or_act(self):
        from datetime import date, timedelta
        from django.test import Client
        from django.urls import reverse
        from django.utils import timezone
        from claims.models import Claim
        from insurance.models import Contract, Insurer, InsuranceLine

        requester = User.objects.create_user(
            username="workflow-end-user-requester",
            password="StrongPass!123",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=requester,
            role=RoleAssignment.Role.INSURED_PERSON,
            company=self.company,
            line_code="*",
            reason="بیمه‌شده برای مشاهده تاریخچه خسارت",
        )
        person = Person.objects.create(
            company=self.company,
            user=requester,
            national_id="8765432109",
            first_name="بیمه‌شده",
            last_name="آزمایش",
            birth_date=date(1990, 1, 1),
        )
        today = timezone.localdate()
        insurer = Insurer.objects.create(name="بیمه‌گر تاریخچه خسارت")
        contract = Contract.objects.create(
            code="WF-HISTORY-CLAIM-CONTRACT",
            title="قرارداد آزمون تاریخچه خسارت",
            insurer=insurer,
            line=InsuranceLine.HEALTH,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=300),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        contract.companies.add(self.company)
        claim = Claim.objects.create(
            claim_number="WF-END-USER-HISTORY",
            person=person,
            contract=contract,
            insurer=insurer,
            service_date=today,
            registered_date=today,
            service_type="هزینه درمان",
            requested_amount=100000,
            assessed_amount=90000,
            payable_amount=80000,
            assessed_by=self.specialist,
            assessed_at=timezone.now(),
            assessment_note="PRIVATE_CLAIM_ASSESSMENT_NOTE",
        )
        case = start_workflow(
            obj=claim,
            code=self.definition.code,
            actor=requester,
            assignee=self.specialist,
            note="PRIVATE_INITIAL_ROUTING_NOTE",
        )
        case = transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="send-to-head",
            recipient=self.department_head,
            note="PRIVATE_INTERNAL_REVIEW_NOTE",
        )

        client = Client()
        client.force_login(requester)
        response = client.get(reverse("workflow_case_detail", args=[case.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, claim.claim_number)
        self.assertNotContains(response, "PRIVATE_CLAIM_ASSESSMENT_NOTE")
        self.assertNotContains(response, "PRIVATE_INITIAL_ROUTING_NOTE")
        self.assertNotContains(response, "PRIVATE_INTERNAL_REVIEW_NOTE")
        self.assertNotContains(response, "ثبت اقدام / ارجاع")

        denied_action = client.post(
            reverse("workflow_case_detail", args=[case.pk]),
            {"action": "send-to-head", "note": "اقدام غیرمجاز"},
        )
        self.assertEqual(denied_action.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.current_assignee_id, self.department_head.pk)

    def test_system_admin_can_unlock_final_lock_and_restore_previous_case_status(self):
        case = start_workflow(
            obj=self.request, code=self.definition.code,
            actor=self.specialist, assignee=self.specialist,
        )
        self.assertEqual(case.status, WorkflowCase.Status.OPEN)
        set_final_lock(case_id=case.pk, actor=self.admin, reason="توقف موقت برای بررسی امنیتی")
        case.refresh_from_db()
        self.assertTrue(case.is_locked)
        self.assertEqual(case.status, WorkflowCase.Status.LOCKED)

        unlock_final_lock(case_id=case.pk, actor=self.admin, reason="بررسی امنیتی پایان یافت")
        case.refresh_from_db()
        self.assertFalse(case.is_locked)
        self.assertEqual(case.status, WorkflowCase.Status.OPEN)
        self.assertTrue(case.events.filter(
            event_type=WorkflowEvent.EventType.UNLOCKED,
            actor=self.admin,
            note="بررسی امنیتی پایان یافت",
        ).exists())

    def test_department_head_cannot_lock_final_case(self):
        case = start_workflow(
            obj=self.request, code=self.definition.code,
            actor=self.specialist, assignee=self.specialist,
        )
        with self.assertRaises(PermissionDenied):
            set_final_lock(case_id=case.pk, actor=self.department_head, reason="قفل غیرمجاز")

    def test_confidential_medical_request_summary_never_exposes_free_text_or_description(self):
        from types import SimpleNamespace

        # The operational recipient must be distinct from the requester;
        # otherwise the test simultaneously expects and denies owner access.
        requester = User.objects.create_user(
            username="workflow-medical-request-owner",
            password="StrongPass!123",
            must_change_password=False,
        )
        self.request.submitted_by = requester
        self.request.title = "نام بیماری محرمانه در عنوان آزاد"
        self.request.description = "شرح پزشکی محرمانه و تشخیص"
        self.request.save(update_fields=[
            "submitted_by", "title", "description", "updated_at"
        ])
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

        owner_summary = build_workflow_presentation(
            case, user=self.request.submitted_by
        )
        self.assertEqual(owner_summary["title"], self.request.title)
        self.assertEqual(owner_summary["description"], self.request.description)

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
        # Position-only routing is intentionally constrained to the requester's
        # organizational branch. Give the request owner a real source assignment
        # so the test exercises same-branch routing rather than an unscoped fallback.
        source_position = OrganizationalPosition.objects.create(
            unit=unit,
            code="WF-POS-SOURCE-SPECIALIST",
            title="کارشناس مبدأ رسیدگی درمان",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        PositionAssignment.objects.create(
            user=self.specialist,
            unit=unit,
            position=source_position,
            line_code="health",
            reason="انتصاب مبدأ سازمانی درخواست آزمایشی",
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

    def test_initial_position_routing_rejects_supervisor_in_unrelated_unit(self):
        from django.core.exceptions import ValidationError
        from accounts.models import OrganizationalPosition, OrganizationalUnit, PositionAssignment
        from requests_portal.models import ServiceRequest

        source_unit = OrganizationalUnit.objects.create(
            code="WF-INITIAL-SOURCE", name="واحد مبدأ گزارش"
        )
        source_position = OrganizationalPosition.objects.create(
            unit=source_unit, code="WF-INITIAL-SOURCE-SPECIALIST",
            title="کارشناس تهیه گزارش", level=OrganizationalPosition.Level.SPECIALIST,
        )
        PositionAssignment.objects.create(
            user=self.specialist, unit=source_unit, position=source_position,
            line_code="health", reason="سمت مبدأ برای آزمون ارجاع اولیه",
        )
        other_unit = OrganizationalUnit.objects.create(
            code="WF-INITIAL-OTHER", name="واحد نامرتبط"
        )
        supervisor_position = OrganizationalPosition.objects.create(
            unit=other_unit, code="WF-INITIAL-OTHER-SUPERVISOR",
            title="سرپرست نامرتبط", level=OrganizationalPosition.Level.SUPERVISOR,
        )
        supervisor = User.objects.create_user(
            username="workflow-initial-unrelated-supervisor",
            password="StrongPass!123",
            must_change_password=False,
        )
        PositionAssignment.objects.create(
            user=supervisor, unit=other_unit, position=supervisor_position,
            line_code="health", reason="سمت خارج از شاخه مبدأ",
        )
        definition = WorkflowDefinition.objects.create(
            code="test-position-initial-scope",
            title="کنترل محدوده ارجاع اولیه",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=definition, code="supervisor-review", title="بررسی سرپرست",
            order=1, allowed_roles=[],
            allowed_position_levels=[int(OrganizationalPosition.Level.SUPERVISOR)],
            is_initial=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()
        item = ServiceRequest.objects.create(
            reference="IB-WF-INITIAL-SCOPE-1",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.specialist,
            company=self.company,
            title="درخواست مبدأ سمت‌محور",
            description="آزمون محدودیت واحد سازمانی",
        )
        with self.assertRaises(ValidationError):
            resolve_initial_assignee(definition=definition, obj=item)

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
            must_change_password=False,
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
            must_change_password=False,
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

        client = Client()
        client.force_login(supervisor)
        with self.assertRaises(PermissionDenied):
            client.get(reverse("workflow_case_detail", args=[case.pk]))

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
            password="StrongPass!123", company=self.company,
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

        # A former participant must be routed to the privacy-safe timeline,
        # never the unrestricted legacy request detail.
        from django.urls import reverse
        client = Client()
        client.force_login(self.specialist)
        detail_response = client.get(
            reverse("request_detail", args=[self.request.pk])
        )
        self.assertEqual(detail_response.status_code, 302)
        self.assertEqual(
            detail_response.url,
            reverse("workflow_case_detail", args=[case.pk]),
        )

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
            username="workflow-snapshot-rep", password="StrongPass!123", company=company_a
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
        unscoped_company = Company.objects.create(code="WF-UNSCOPED", name="شرکت بدون محدوده")
        representative = User.objects.create_user(
            username="workflow-unscoped-rep", password="StrongPass!123",
            company=unscoped_company,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=unscoped_company,
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
            username="workflow-rep", password="StrongPass!123", company=company_a
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



    def test_published_workflow_is_versioned_without_mutating_the_published_record(self):
        original = WorkflowDefinition.objects.get(pk=self.definition.pk)
        original_title = original.title
        original_published_at = original.published_at

        original.is_active = False
        original.save(update_fields=["is_active"])

        next_definition = WorkflowDefinition.objects.create(
            code=original.code,
            title="Workflow test - version two",
            version=original.version + 1,
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=next_definition,
            code="specialist-v2",
            title="Specialist version two",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
            is_initial=True,
        )
        next_definition.approved_by = self.admin
        next_definition.is_active = True
        next_definition.save()

        original.refresh_from_db()
        self.assertEqual(original.title, original_title)
        self.assertEqual(original.version, 1)
        self.assertEqual(original.published_at, original_published_at)
        self.assertFalse(original.is_active)
        self.assertEqual(next_definition.version, 2)
        self.assertIsNotNone(next_definition.published_at)
        self.assertEqual(
            WorkflowDefinition.objects.filter(code=original.code, is_active=True).count(),
            1,
        )
        self.assertEqual(
            WorkflowDefinition.objects.get(code=original.code, is_active=True).pk,
            next_definition.pk,
        )

        next_definition.title = "Attempted published workflow edit"
        with self.assertRaises(ValidationError):
            next_definition.save()

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


    def test_initial_routing_rejects_inactive_company_and_insurer_scopes(self):
        today = timezone.localdate()

        inactive_company = Company.objects.create(
            code="WF-INACTIVE-ROUTE-CO",
            name="شرکت غیرفعال برای آزمون ارجاع",
        )
        company_rep = User.objects.create_user(
            username="workflow-inactive-company-rep",
            password="StrongPass!123",
            company=inactive_company,
        )
        RoleAssignment.objects.create(
            user=company_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=inactive_company,
            line_code="health",
            valid_from=today,
            reason="انتصاب پیش از غیرفعال‌سازی شرکت",
        )
        inactive_company.is_active = False
        inactive_company.save(update_fields=["is_active"])

        company_definition = WorkflowDefinition.objects.create(
            code="test-inactive-company-routing",
            title="عدم ارجاع به نماینده شرکت غیرفعال",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=company_definition,
            code="company-review",
            title="بررسی شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        with self.assertRaises(ValidationError):
            resolve_initial_assignee(
                definition=company_definition,
                company_id=inactive_company.pk,
                line_code="health",
            )

        inactive_insurer = Insurer.objects.create(
            name="بیمه‌گر غیرفعال برای آزمون ارجاع",
        )
        insurer_rep = User.objects.create_user(
            username="workflow-inactive-insurer-rep",
            password="StrongPass!123",
        )
        RoleAssignment.objects.create(
            user=insurer_rep,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=inactive_insurer,
            valid_from=today,
            reason="انتصاب پیش از غیرفعال‌سازی بیمه‌گر",
        )
        inactive_insurer.is_active = False
        inactive_insurer.save(update_fields=["is_active"])

        insurer_definition = WorkflowDefinition.objects.create(
            code="test-inactive-insurer-routing",
            title="عدم ارجاع به نماینده بیمه‌گر غیرفعال",
            created_by=self.admin,
        )
        WorkflowStep.objects.create(
            definition=insurer_definition,
            code="insurer-review",
            title="بررسی بیمه‌گر",
            order=1,
            allowed_roles=[RoleAssignment.Role.INSURER_REP],
            is_initial=True,
        )
        with self.assertRaises(ValidationError):
            resolve_initial_assignee(
                definition=insurer_definition,
                insurer_id=inactive_insurer.pk,
                line_code="health",
            )


class WorkflowSatisfactionTests(TestCase):
    def setUp(self):
        from django.contrib.contenttypes.models import ContentType
        from accounts.models import User
        from organizations.models import Company
        from requests_portal.models import ServiceRequest
        from workflow.models import WorkflowCase, WorkflowDefinition

        self.owner = User.objects.create_user(
            username="workflow-survey-owner",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.other = User.objects.create_user(
            username="workflow-survey-other",
            password="StrongPass!2026",
            must_change_password=False,
        )
        company = Company.objects.create(code="WF-SURVEY", name="شرکت نظرسنجی")
        item = ServiceRequest.objects.create(
            reference="IB-WF-SURVEY-1",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.owner,
            company=company,
            title="درخواست نظرسنجی",
            description="شرح",
        )
        definition = WorkflowDefinition.objects.create(
            code="workflow-survey-test",
            title="آزمون نظرسنجی",
            created_by=self.owner,
        )
        self.case = WorkflowCase.objects.create(
            definition=definition,
            content_type=ContentType.objects.get_for_model(item, for_concrete_model=False),
            object_id=str(item.pk),
            status=WorkflowCase.Status.CLOSED,
        )

    def test_request_owner_can_submit_one_immutable_satisfaction_survey(self):
        from django.urls import reverse
        from workflow.models import WorkflowSatisfactionSurvey

        client = Client()
        client.force_login(self.owner)
        response = client.post(
            reverse("workflow_satisfaction_submit", args=[self.case.pk]),
            {"rating": "5", "comment": "فرایند شفاف و قابل پیگیری بود."},
        )
        self.assertEqual(response.status_code, 302)
        survey = WorkflowSatisfactionSurvey.objects.get(
            workflow_case=self.case, respondent=self.owner
        )
        self.assertEqual(survey.rating, 5)
        self.assertEqual(survey.comment, "فرایند شفاف و قابل پیگیری بود.")

        response = client.post(
            reverse("workflow_satisfaction_submit", args=[self.case.pk]),
            {"rating": "1", "comment": "تلاش برای تغییر پاسخ"},
        )
        self.assertEqual(response.status_code, 200)
        survey.refresh_from_db()
        self.assertEqual(survey.rating, 5)

    def test_unrelated_user_cannot_submit_satisfaction_survey(self):
        from django.core.exceptions import PermissionDenied
        from django.urls import reverse

        client = Client()
        client.force_login(self.other)
        with self.assertRaises(PermissionDenied):
            client.get(reverse("workflow_satisfaction_submit", args=[self.case.pk]))


class OperationalWorkflowSeedCommandTests(TestCase):
    def test_seed_command_publishes_new_version_when_active_baseline_is_outdated(self):
        from django.core.management import call_command
        from accounts.models import RoleAssignment
        from workflow.models import WorkflowDefinition, WorkflowStep

        head = User.objects.create_user(
            username="workflow-seed-upgrade-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای ارتقای گردش‌کار",
        )
        old = WorkflowDefinition.objects.create(
            code="other",
            title="گردش قدیمی درخواست",
            version=1,
            created_by=head,
            description="تعریف قدیمی بدون نسخه مسیر جدید",
        )
        WorkflowStep.objects.create(
            definition=old,
            code="submitted",
            title="ثبت‌شده",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        old.approved_by = head
        old.is_active = True
        old.save()

        call_command("seed_operational_workflows")
        old.refresh_from_db()
        current = WorkflowDefinition.objects.get(code="other", is_active=True)
        self.assertFalse(old.is_active)
        self.assertEqual(current.version, 2)
        self.assertIn("baseline-route-v3", current.description)
        self.assertEqual(old.steps.count(), 1)

    def test_seed_command_rebases_open_cases_to_new_definition_and_preserves_history(self):
        from django.core.management import call_command
        from accounts.models import RoleAssignment
        from organizations.models import Company
        from requests_portal.models import ServiceRequest
        from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowEvent, WorkflowStep
        from workflow.services import start_workflow

        head = User.objects.create_user(
            username="workflow-rebase-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای مهاجرت گردش",
        )
        company = Company.objects.create(code="WF-REBASE-COMP", name="شرکت مهاجرت گردش")
        representative = User.objects.create_user(
            username="workflow-rebase-rep",
            password="StrongPass!2026",
            must_change_password=False, company=company,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company,
            line_code="*",
            reason="نماینده شرکت برای مهاجرت گردش",
        )
        old = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.OTHER,
            title="گردش قدیمی سایر درخواست‌ها",
            version=1,
            created_by=head,
            description="نسخه قدیمی",
        )
        WorkflowStep.objects.create(
            definition=old,
            code=ServiceRequest.Status.SUBMITTED,
            title="ثبت‌شده",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        old.approved_by = head
        old.is_active = True
        old.save()
        item = ServiceRequest.objects.create(
            reference="IB-WF-REBASE-1",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=representative,
            company=company,
            title="درخواست در حال گردش",
            description="آزمون حفظ تاریخچه نسخه",
        )
        case = start_workflow(
            obj=item,
            code=ServiceRequest.Kind.OTHER,
            actor=head,
            assignee=representative,
        )
        previous_event_count = case.events.count()

        call_command("seed_operational_workflows")
        case.refresh_from_db()
        active = WorkflowDefinition.objects.get(code=ServiceRequest.Kind.OTHER, is_active=True)
        self.assertEqual(case.definition_id, active.pk)
        self.assertEqual(case.current_step.code, ServiceRequest.Status.SUBMITTED)
        self.assertEqual(case.current_assignee_id, representative.pk)
        self.assertEqual(case.events.count(), previous_event_count + 1)
        self.assertTrue(case.events.filter(action_code="workflow_version_migrated").exists())
        self.assertEqual(WorkflowCase.objects.filter(
            definition=active, content_type=case.content_type, object_id=case.object_id
        ).count(), 1)

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
            "management_report_approval",
        } | set(ServiceRequest.Kind.values)
        active = set(
            WorkflowDefinition.objects.filter(is_active=True).values_list("code", flat=True)
        )
        self.assertTrue(expected.issubset(active))
        for kind in ServiceRequest.Kind.values:
            definition = WorkflowDefinition.objects.get(code=kind, is_active=True)
            self.assertFalse(definition.steps.filter(code=ServiceRequest.Status.CLOSED).exists())

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
