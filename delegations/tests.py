from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserNotification
from organizations.models import Company, Person, PersonChangeRequest
from workflow.models import WorkflowDefinition, WorkflowStep
from workflow.services import is_delegated_assignee, resolve_initial_assignee, start_workflow, transition_case
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowTransition

from .forms import WorkDelegationForm
from .models import WorkDelegation
from .services import (
    _role_assignment_is_active,
    apply_delegation_to_open_cases,
    synchronize_delegations,
    update_delegation_status,
)


User = get_user_model()


class DelegationRoutingTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.head = User.objects.create_user(username="delegation.head", password="TestPass!23456", must_change_password=False)
        RoleAssignment.objects.create(
            user=self.head, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            is_active=True, valid_from=today,
        )
        self.company = Company.objects.create(code="DELEGATION-CO", name="شرکت آزمون تفویض")
        self.representative = User.objects.create_user(username="delegation.rep", password="TestPass!23456", must_change_password=False, company=self.company)
        RoleAssignment.objects.create(
            user=self.representative, role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company, line_code="health", is_active=True, valid_from=today,
        )
        self.specialist = User.objects.create_user(username="delegation.health", password="TestPass!23456", must_change_password=False)
        RoleAssignment.objects.create(
            user=self.specialist, role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health", is_active=True, valid_from=today,
        )
        self.definition = WorkflowDefinition.objects.create(
            code="person_change", title="اصلاح اطلاعات", version=77, created_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=self.definition, code="company_review",
            title="بررسی اولیه", order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP], is_initial=True,
        )
        self.definition.approved_by = self.head
        self.definition.is_active = True
        self.definition.save()

    def test_iban_delegation_routes_only_matching_change_type_to_specialist(self):
        rule = WorkDelegation.objects.create(
            workflow_code="person_change", item_type="iban",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist, granted_by=self.head,
            company=self.company, line_code="health",
            reason="رسیدگی تخصصی به تمام اصلاح‌های شبا",
            valid_from=timezone.localdate(),
        )
        assignee, matched = resolve_initial_assignee(
            definition=self.definition, company_id=self.company.pk,
            line_code="health", item_type="iban", return_delegation=True,
        )
        self.assertEqual(assignee, self.specialist)
        self.assertEqual(matched, rule)

    def test_unrelated_person_change_keeps_normal_company_assignment(self):
        assignee, matched = resolve_initial_assignee(
            definition=self.definition, company_id=self.company.pk,
            line_code="health", item_type="mobile", return_delegation=True,
        )
        self.assertEqual(assignee, self.representative)
        self.assertIsNone(matched)

    def test_request_owner_receives_start_and_progress_notifications(self):
        beneficiary = User.objects.create_user(
            username="delegation.beneficiary",
            password="TestPass!23456",
            role="employee",
            company=self.company,
            must_change_password=False,
        )
        person = Person.objects.create(
            company=self.company,
            user=beneficiary,
            national_id=f"9{beneficiary.pk:09d}",
            first_name="بیمه‌شده",
            last_name="آزمایشی",
            birth_date=timezone.localdate() - timedelta(days=10000),
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=83,
            created_by=self.head,
            approved_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        review = WorkflowStep.objects.create(
            definition=definition,
            code="head_review",
            title="بررسی رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=review,
            action_code="refer_to_head",
            title="ارجاع برای تصمیم",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.is_active = True
        definition.save()
        item = ServiceRequest.objects.create(
            reference="DELEGATION-OWNER-NOTICE",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            person=person,
            company=self.company,
            title="درخواست درمان ثبت‌شده توسط نماینده",
            description="متن محرمانه درخواست",
            is_confidential=True,
        )

        case = start_workflow(
            obj=item,
            code=item.kind,
            actor=self.representative,
            assignee=self.representative,
            note="درخواست از طرف بیمه‌شده ثبت شد.",
        )

        start_notice = UserNotification.objects.get(
            recipient=beneficiary,
            target_url=reverse("request_detail", args=[item.pk]),
        )
        self.assertEqual(start_notice.title, "درخواست شما در سامانه ثبت شد")

        transition_case(
            case_id=case.pk,
            actor=self.representative,
            action_code="refer_to_head",
            recipient=self.head,
            note="برای تصمیم نهایی ارسال شد.",
        )
        self.assertTrue(UserNotification.objects.filter(
            recipient=beneficiary,
            title="وضعیت درخواست شما به‌روزرسانی شد",
            target_url=reverse("request_detail", args=[item.pk]),
        ).exists())

    def test_delegate_can_receive_and_act_on_scoped_initial_work(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=78,
            created_by=self.head,
            approved_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        review = WorkflowStep.objects.create(
            definition=definition,
            code="head_review",
            title="بررسی رئیس اداره",
            order=2,
            allowed_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=review,
            action_code="refer_to_head",
            title="ارجاع برای تصمیم",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            recipient_roles=[RoleAssignment.Role.DEPARTMENT_HEAD],
        )
        definition.is_active = True
        definition.save()
        request = ServiceRequest.objects.create(
            reference="DELEGATION-REQ-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست آزمایشی",
            description="آزمون تفویض اختیار",
            is_confidential=True,
        )
        rule = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="رسیدگی تخصصی به درخواست‌های درمانی",
            valid_from=timezone.localdate(),
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=request,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=request,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(assignee, self.specialist)
        self.assertEqual(case.delegation, rule)
        self.assertTrue(is_delegated_assignee(case, self.specialist))
        transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="refer_to_head",
            recipient=self.head,
            note="بررسی اولیه انجام شد.",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_assignee, self.head)
        self.assertIsNone(case.delegation_id)
        self.assertFalse(is_delegated_assignee(case, self.specialist))
        self.assertEqual(
            case.events.order_by("-pk").first().metadata["delegation_id"],
            rule.pk,
        )

    def test_delegation_expires_when_case_advances_even_if_delegate_remains_assignee(self):
        definition = WorkflowDefinition.objects.create(
            code="delegation-same-recipient",
            title="گردش آزمون پایان تفویض در مرحله بعد",
            created_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company-intake",
            title="دریافت اولیه شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        specialist_step = WorkflowStep.objects.create(
            definition=definition,
            code="specialist-review",
            title="بررسی تخصصی",
            order=2,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            target_step=specialist_step,
            action_code="continue-with-specialist",
            title="ادامه با کارشناس",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            recipient_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
        )
        definition.approved_by = self.head
        definition.is_active = True
        definition.save()

        rule = WorkDelegation.objects.create(
            workflow_code=definition.code,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="پوشش مرحله آغازین تا ارجاع به مرحله تخصصی",
            valid_from=timezone.localdate(),
        )
        item = ServiceRequest.objects.create(
            reference="DELEGATION-SAME-RECIPIENT-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست انتقال از مرحله تفویض",
            description="پس از ورود به مرحله بعد باید مجوز نقش مقصد اعمال شود.",
        )
        case = start_workflow(
            obj=item,
            code=definition.code,
            actor=self.representative,
            assignee=self.specialist,
            delegation=rule,
        )
        self.assertTrue(is_delegated_assignee(case, self.specialist))

        case = transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="continue-with-specialist",
            recipient=self.specialist,
            note="ارجاع به مرحله تخصصی با نقش واقعی کارشناس.",
        )
        case.refresh_from_db()
        self.assertEqual(case.current_step_id, specialist_step.pk)
        self.assertEqual(case.current_assignee_id, self.specialist.pk)
        self.assertIsNone(case.delegation_id)
        self.assertFalse(is_delegated_assignee(case, self.specialist))

        from workflow.services import mark_case_opened
        mark_case_opened(case_id=case.pk, actor=self.specialist)

    def test_company_representative_delegation_requires_explicit_line_scope(self):
        today = timezone.localdate()
        blank_line_rep = User.objects.create_user(
            username="delegation.rep.blank-line",
            password="TestPass!23456",
            must_change_password=False,
            company=self.company,
        )
        RoleAssignment.objects.create(
            user=blank_line_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="",
            valid_from=today,
        )
        health_rep = self.representative
        all_lines_rep = User.objects.create_user(
            username="delegation.rep.all-lines",
            password="TestPass!23456",
            must_change_password=False,
            company=self.company,
        )
        RoleAssignment.objects.create(
            user=all_lines_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="*",
            valid_from=today,
        )

        def delegation_for(user, line_code):
            return WorkDelegation(
                delegate_role=RoleAssignment.Role.SUBSIDIARY_REP,
                delegate_to=user,
                company=self.company,
                line_code=line_code,
                valid_from=today,
            )

        self.assertFalse(_role_assignment_is_active(
            delegation_for(blank_line_rep, "health")
        ))
        self.assertFalse(_role_assignment_is_active(
            delegation_for(blank_line_rep, "")
        ))
        self.assertTrue(_role_assignment_is_active(
            delegation_for(health_rep, "health")
        ))
        self.assertFalse(_role_assignment_is_active(
            delegation_for(health_rep, "")
        ))
        self.assertTrue(_role_assignment_is_active(
            delegation_for(all_lines_rep, "health")
        ))
        self.assertTrue(_role_assignment_is_active(
            delegation_for(all_lines_rep, "")
        ))

    def test_company_representative_form_filters_recipients_by_line_scope(self):
        today = timezone.localdate()
        blank_line_rep = User.objects.create_user(
            username="delegation.form.blank-line",
            password="TestPass!23456",
            must_change_password=False,
            company=self.company,
        )
        RoleAssignment.objects.create(
            user=blank_line_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="",
            valid_from=today,
        )
        health_rep = self.representative
        all_lines_rep = User.objects.create_user(
            username="delegation.form.all-lines",
            password="TestPass!23456",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=all_lines_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="*",
            valid_from=today,
        )

        base_data = {
            "workflow_code": "person_change",
            "item_type": "iban",
            "delegate_role": RoleAssignment.Role.SUBSIDIARY_REP,
            "delegate_to": str(health_rep.pk),
            "company": str(self.company.pk),
            "insurer": "",
            "line_code": "health",
            "valid_from": today.isoformat(),
            "valid_until": "",
            "reason": "پوشش کنترل‌شده اصلاح اطلاعات در رشته درمان",
        }
        scoped_form = WorkDelegationForm(data=base_data)
        scoped_ids = set(scoped_form.fields["delegate_to"].queryset.values_list("pk", flat=True))
        self.assertEqual(scoped_ids, {health_rep.pk, all_lines_rep.pk})

        all_lines_data = {**base_data, "line_code": "", "delegate_to": str(all_lines_rep.pk)}
        all_lines_form = WorkDelegationForm(data=all_lines_data)
        all_lines_ids = set(all_lines_form.fields["delegate_to"].queryset.values_list("pk", flat=True))
        self.assertEqual(all_lines_ids, {all_lines_rep.pk})

        invalid_form = WorkDelegationForm(data={
            **base_data,
            "delegate_to": str(blank_line_rep.pk),
        })
        self.assertFalse(invalid_form.is_valid())
        self.assertIn("delegate_to", invalid_form.errors)

    def test_more_specific_rule_wins_over_broader_rule(self):
        backup = User.objects.create_user(
            username="delegation.health.backup", password="TestPass!23456"
        )
        RoleAssignment.objects.create(
            user=backup,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=timezone.localdate(),
        )
        WorkDelegation.objects.create(
            workflow_code="person_change",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            line_code="health",
            reason="تفویض عمومی رشته درمان",
            valid_from=timezone.localdate(),
        )
        specific = WorkDelegation.objects.create(
            workflow_code="person_change",
            item_type="iban",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=backup,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض تخصصی اصلاح شبا در این شرکت",
            valid_from=timezone.localdate(),
        )

        assignee, matched = resolve_initial_assignee(
            definition=self.definition,
            company_id=self.company.pk,
            line_code="health",
            item_type="iban",
            return_delegation=True,
        )

        self.assertEqual(assignee, backup)
        self.assertEqual(matched, specific)

    def test_revoking_delegation_after_case_left_initial_stage_does_not_apply_intake_rule(self):
        backup = User.objects.create_user(
            username="delegation.later-stage.backup",
            password="TestPass!23456",
        )
        RoleAssignment.objects.create(
            user=backup,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=timezone.localdate(),
        )
        # Published workflow versions are immutable. Create and publish a
        # successor version instead of adding a step to the active definition.
        self.definition.is_active = False
        self.definition.save(update_fields=["is_active"])
        definition = WorkflowDefinition.objects.create(
            code="person_change",
            title="اصلاح اطلاعات ـ نسخه مرحله تخصصی",
            version=78,
            created_by=self.head,
        )
        initial_step = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        later_step = WorkflowStep.objects.create(
            definition=definition,
            code="specialist_review",
            title="بررسی تخصصی",
            order=2,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial_step,
            target_step=later_step,
            action_code="send-to-specialist-stage",
            title="ورود به بررسی تخصصی",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            recipient_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST],
        )
        definition.approved_by = self.head
        definition.is_active = True
        definition.save()

        from insurance.models import Contract, Insurer, InsuranceLine
        today = timezone.localdate()
        insurer = Insurer.objects.create(name="بیمه‌گر مرحله تخصصی تفویض")
        contract = Contract.objects.create(
            code="DELEGATION-LATER-CONTRACT",
            title="قرارداد آزمون مرحله تخصصی",
            insurer=insurer,
            line=InsuranceLine.HEALTH,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=365),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        contract.companies.add(self.company)
        person = Person.objects.create(
            company=self.company,
            user=self.representative,
            national_id="9812345678",
            first_name="بیمه‌شده",
            last_name="آزمون تفویض",
            birth_date=today - timedelta(days=12000),
            iban="IR120000000000000000000000",
        )
        self.request = PersonChangeRequest.objects.create(
            person=person,
            company=self.company,
            contract=contract,
            requested_by=self.representative,
            change_type=PersonChangeRequest.ChangeType.IBAN,
            current_value=person.iban,
            requested_value="IR340000000000000000000000",
            reason="آزمون انتقال پرونده پس از خروج از مرحله آغازین",
        )

        broad = WorkDelegation.objects.create(
            workflow_code="person_change",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=backup,
            granted_by=self.head,
            line_code="health",
            reason="تفویض عمومی مرحله آغازین",
            valid_from=timezone.localdate(),
        )
        specific = WorkDelegation.objects.create(
            workflow_code="person_change",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض اختصاصی مرحله آغازین شرکت",
            valid_from=timezone.localdate(),
        )
        case = start_workflow(
            obj=self.request,
            code="person_change",
            actor=self.representative,
            assignee=self.specialist,
            delegation=specific,
        )
        transition_case(
            case_id=case.pk,
            actor=self.specialist,
            action_code="send-to-specialist-stage",
            recipient=self.specialist,
            note="پرونده وارد مرحله تخصصی شد.",
        )

        update_delegation_status(
            delegation_id=specific.pk,
            actor=self.head,
            action="revoke",
            reason="پایان مسئولیت در این محدوده",
        )

        case.refresh_from_db()
        self.assertEqual(case.current_step, later_step)
        self.assertEqual(case.current_assignee, self.head)
        self.assertIsNone(case.delegation_id)
        broad.refresh_from_db()
        self.assertEqual(broad.status, WorkDelegation.Status.ACTIVE)

    def test_revoking_specific_rule_routes_open_cases_to_broader_valid_rule(self):
        backup = User.objects.create_user(
            username="delegation.health.backup", password="TestPass!23456"
        )
        RoleAssignment.objects.create(
            user=backup,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=timezone.localdate(),
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=79,
            created_by=self.head,
            approved_by=self.head,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        broad = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            line_code="health",
            reason="تفویض عمومی درخواست‌های درمانی",
            valid_from=timezone.localdate(),
        )
        specific = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=backup,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض اختصاصی این شرکت",
            valid_from=timezone.localdate(),
        )
        request = ServiceRequest.objects.create(
            reference="DELEGATION-REQ-REVOKE",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست آزمایش برگشت تفویض",
            description="آزمون جایگزینی قانون تفویض",
            is_confidential=True,
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=request,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=request,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(case.current_assignee, backup)
        self.assertEqual(case.delegation, specific)

        update_delegation_status(
            delegation_id=specific.pk,
            actor=self.head,
            action="revoke",
            reason="تغییر در تقسیم مسئولیت‌ها",
        )

        case.refresh_from_db()
        self.assertEqual(case.current_assignee, self.specialist)
        self.assertEqual(case.delegation, broad)
        self.assertTrue(
            case.events.filter(
                action_code="delegation_route",
                metadata__delegation_id=broad.pk,
            ).exists()
        )

    def test_creating_category_rule_routes_existing_open_initial_cases(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=81,
            created_by=self.head,
            approved_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        item = ServiceRequest.objects.create(
            reference="DELEGATION-BULK-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="پرونده باز پیش از تفویض",
            description="آزمون انتقال پرونده‌های جاری",
            is_confidential=True,
        )
        case = start_workflow(
            obj=item,
            code=item.kind,
            actor=self.representative,
            assignee=self.representative,
        )
        self.assertEqual(case.current_assignee, self.representative)
        rule = WorkDelegation.objects.create(
            workflow_code=item.kind,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="واگذاری دسته‌ای پرونده‌های درمان",
            valid_from=timezone.localdate(),
        )

        routed = apply_delegation_to_open_cases(rule, actor=self.head)

        case.refresh_from_db()
        self.assertEqual(routed, 1)
        self.assertEqual(case.current_assignee, self.specialist)
        self.assertEqual(case.delegation, rule)
        self.assertTrue(case.events.filter(
            action_code="delegation_route",
            metadata__delegation_id=rule.pk,
        ).exists())
        self.assertTrue(UserNotification.objects.filter(
            recipient=self.specialist,
            target_url=reverse("workflow_case_detail", args=[case.pk]),
        ).exists())

    def test_bulk_delegation_never_routes_requester_to_themselves(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=82,
            created_by=self.head,
            approved_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        item = ServiceRequest.objects.create(
            reference="DELEGATION-SELF-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.specialist,
            company=self.company,
            title="درخواست شخصی کارشناس",
            description="نباید به خود درخواست‌دهنده واگذار شود",
            is_confidential=True,
        )
        case = start_workflow(
            obj=item,
            code=item.kind,
            actor=self.specialist,
            assignee=self.representative,
        )
        rule = WorkDelegation.objects.create(
            workflow_code=item.kind,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="آزمون جلوگیری از واگذاری به درخواست‌دهنده",
            valid_from=timezone.localdate(),
        )

        routed = apply_delegation_to_open_cases(rule, actor=self.head)

        case.refresh_from_db()
        self.assertEqual(routed, 0)
        self.assertEqual(case.current_assignee, self.representative)
        self.assertIsNone(case.delegation_id)

    def test_recipient_inbox_shows_assigned_work_and_creates_notification(self):
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="درخواست درمان",
            version=80,
            created_by=self.head,
            approved_by=self.head,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()
        rule = WorkDelegation.objects.create(
            workflow_code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=self.specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="رسیدگی درخواست‌های درمانی این شرکت",
            valid_from=timezone.localdate(),
        )
        item = ServiceRequest.objects.create(
            reference="DELEGATION-INBOX-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.representative,
            company=self.company,
            title="درخواست نمایشی صندوق گیرنده",
            description="آزمون نمایش در پنل گیرنده",
            is_confidential=True,
        )
        assignee, matched = resolve_initial_assignee(
            definition=definition,
            obj=item,
            company_id=self.company.pk,
            line_code="health",
            owner_user_id=self.representative.pk,
            return_delegation=True,
        )
        case = start_workflow(
            obj=item,
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            actor=self.representative,
            assignee=assignee,
            delegation=matched,
        )
        self.assertEqual(case.delegation, rule)
        self.assertTrue(UserNotification.objects.filter(
            recipient=self.specialist,
            target_url=reverse("workflow_case_detail", args=[case.pk]),
        ).exists())

        client = Client()
        client.force_login(self.specialist)
        inbox = client.get(reverse("delegation_inbox"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "کارهای تفویض‌شده به من")
        self.assertContains(inbox, "پرونده محرمانه")
        self.assertNotContains(inbox, "درخواست نمایشی صندوق گیرنده")
        self.assertContains(inbox, "درخواست درمان")
        dashboard = client.get(reverse("dashboard"))
        self.assertContains(dashboard, reverse("delegation_inbox"))

    def test_unrelated_user_cannot_open_or_see_delegation_inbox(self):
        unrelated = User.objects.create_user(
            username="delegation.unrelated",
            password="TestPass!23456",
            must_change_password=False,
        )
        client = Client()
        client.force_login(unrelated)
        inbox = client.get(reverse("delegation_inbox"))
        self.assertEqual(inbox.status_code, 403)
        dashboard = client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, reverse("delegation_inbox"))

    def test_global_manager_can_open_delegation_management(self):
        client = Client()
        client.force_login(self.head)
        response = client.get(reverse("delegation_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "مدیریت تفویض اختیار")

    def test_delegation_form_lists_recipient_whose_assignment_starts_on_future_date(self):
        start_date = timezone.localdate() + timedelta(days=15)
        future_specialist = User.objects.create_user(
            username="delegation.future.form",
            password="TestPass!23456",
        )
        RoleAssignment.objects.create(
            user=future_specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=start_date,
            reason="انتصاب آتی برای آزمون فرم تفویض",
        )
        form = WorkDelegationForm(data={
            "workflow_code": "person_change",
            "item_type": "iban",
            "delegate_role": RoleAssignment.Role.INSURANCE_SPECIALIST,
            "delegate_to": str(future_specialist.pk),
            "company": str(self.company.pk),
            "insurer": "",
            "line_code": "health",
            "valid_from": start_date.isoformat(),
            "valid_until": "",
            "reason": "تفویض از تاریخ شروع انتصاب آتی کارشناس",
        })

        self.assertIn(
            future_specialist,
            form.fields["delegate_to"].queryset,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_future_dated_delegation_is_not_suspended_before_its_start(self):
        start_date = timezone.localdate() + timedelta(days=10)
        future_specialist = User.objects.create_user(
            username="delegation.future.health",
            password="TestPass!23456",
        )
        RoleAssignment.objects.create(
            user=future_specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            is_active=True,
            valid_from=start_date,
            reason="انتصاب آتی کارشناس",
        )
        rule = WorkDelegation.objects.create(
            workflow_code="person_change",
            item_type="iban",
            delegate_role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            delegate_to=future_specialist,
            granted_by=self.head,
            company=self.company,
            line_code="health",
            reason="تفویض با تاریخ شروع آینده",
            valid_from=start_date,
        )

        report = synchronize_delegations()

        rule.refresh_from_db()
        self.assertEqual(rule.status, WorkDelegation.Status.ACTIVE)
        self.assertEqual(report["suspended"], 0)
        self.assertEqual(rule.revocation_reason, "")

    def test_ambiguous_delegation_rules_are_blocked(self):
        common = {
            "workflow_code": "person_change",
            "item_type": "iban",
            "delegate_role": RoleAssignment.Role.INSURANCE_SPECIALIST,
            "delegate_to": self.specialist,
            "granted_by": self.head,
            "line_code": "health",
            "reason": "تفویض آزمون",
            "valid_from": timezone.localdate(),
        }
        WorkDelegation.objects.create(**common, company=self.company)
        WorkDelegation.objects.create(**common, company=self.company)
        with self.assertRaises(ValidationError):
            resolve_initial_assignee(
                definition=self.definition, company_id=self.company.pk,
                line_code="health", item_type="iban",
            )
