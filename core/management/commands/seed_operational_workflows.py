from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Max
from django.utils import timezone

from accounts.models import RoleAssignment
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowEvent, WorkflowStep, WorkflowTransition
from workflow.services import _scope_for_object, _validate_recipient, is_delegated_assignee


class Command(BaseCommand):
    help = "Publish versioned operational workflows; preserve historical definitions and cases."
    BASELINE_SCHEMA_VERSION = "baseline-route-v2"

    WORKFLOWS = (
        ("contract_approval", "تأیید قرارداد", "approved"),
        ("contract_termination", "تأیید فسخ قرارداد", "terminated"),
        ("asset_valuation_approval", "تأیید ارزیابی دارایی", "approved"),
        ("asset_policy_approval", "تأیید دوره بیمه‌نامه دارایی", "approved"),
        ("asset_endorsement_approval", "تأیید الحاقیه دارایی", "approved"),
        ("person_change", "اصلاح اطلاعات بیمه‌شده", "approved"),
        ("claim_review", "ارزیابی و تصمیم خسارت", "approved"),
        ("claim_objection", "رسیدگی به اعتراض خسارت", "closed"),
    )

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()
        global_roles = [
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.SYSTEM_ADMIN,
        ]
        assignment = (
            RoleAssignment.objects.filter(
                role__in=global_roles,
                is_active=True,
                valid_from__lte=today,
                user__is_active=True,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
            .select_related("user")
            .order_by("pk")
            .first()
        )
        if not assignment:
            raise CommandError(
                "No active Department Head/System Admin RoleAssignment exists. "
                "Create a valid global role assignment before seeding workflows."
            )

        actor = assignment.user
        created = []
        skipped = []
        for code, title, approved_step_code in self.WORKFLOWS:
            active = WorkflowDefinition.objects.filter(code=code, is_active=True).first()
            if active and self.BASELINE_SCHEMA_VERSION in active.description:
                self._rebase_open_cases(code, active, actor)
                skipped.append(code)
                continue
            if active:
                # Published definitions remain immutable; only their active
                # pointer is retired. Existing cases retain their old version.
                active.is_active = False
                active.save(update_fields=["is_active"])
            version = (
                WorkflowDefinition.objects.filter(code=code)
                .aggregate(value=Max("version"))["value"] or 0
            ) + 1
            definition = WorkflowDefinition.objects.create(
                code=code,
                title=title,
                version=version,
                created_by=actor,
                description=(
                    f"{self.BASELINE_SCHEMA_VERSION}: گردش پایه نسخه‌دار. تغییر مسیر فقط با ایجاد و انتشار نسخه جدید "
                    "و تأیید رئیس اداره بیمه یا مدیر سامانه مجاز است."
                ),
            )
            if code == "person_change":
                self._build_person_change(definition)
            elif code == "claim_review":
                self._build_claim_review(definition, global_roles)
            elif code == "claim_objection":
                self._build_claim_objection(definition, global_roles)
            else:
                self._build_global_approval(definition, approved_step_code, global_roles)
            definition.approved_by = actor
            definition.is_active = True
            definition.save()
            self._rebase_open_cases(code, definition, actor)
            created.append(code)

        # Every ServiceRequest kind is routed through the same audited state
        # contract, while each kind keeps its own immutable workflow definition.
        for code, title in ServiceRequest.Kind.choices:
            active = WorkflowDefinition.objects.filter(code=code, is_active=True).first()
            if active and self.BASELINE_SCHEMA_VERSION in active.description:
                self._rebase_open_cases(code, active, actor)
                skipped.append(code)
                continue
            if active:
                active.is_active = False
                active.save(update_fields=["is_active"])
            version = (
                WorkflowDefinition.objects.filter(code=code)
                .aggregate(value=Max("version"))["value"] or 0
            ) + 1
            definition = WorkflowDefinition.objects.create(
                code=code,
                title=f"گردش درخواست: {title}",
                version=version,
                created_by=actor,
                description=(
                    f"{self.BASELINE_SCHEMA_VERSION}: گردش استاندارد درخواست پرتال. مسیرها با نسخه جدید و "
                    "تأیید رئیس اداره بیمه یا مدیر سامانه تغییر می‌کنند."
                ),
            )
            self._build_service_request(definition, global_roles)
            definition.approved_by = actor
            definition.is_active = True
            definition.save()
            self._rebase_open_cases(code, definition, actor)
            created.append(code)

        if created:
            self.stdout.write(self.style.SUCCESS("Created and published: " + ", ".join(created)))
        if skipped:
            self.stdout.write("Already active; left unchanged: " + ", ".join(skipped))
        self.stdout.write(
            "Contract and asset approvals are restricted to Department Head/System Admin. "
            "Person changes follow Company Representative → Insurer Representative → "
            "Company Representative; insurer representatives cannot close requests."
        )

    def _rebase_open_cases(self, code, definition, actor):
        """Move open cases to the active version without discarding event history.

        Every case is prevalidated against the new step's scope. If its owner
        no longer qualifies, the whole seed transaction rolls back instead of
        silently granting access or orphaning an active case.
        """
        cases = WorkflowCase.objects.filter(
            definition__code=code,
            status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        ).exclude(definition=definition).select_related(
            "definition", "current_step", "current_assignee",
            "current_position_assignment", "delegation", "content_type",
        ).order_by("pk")
        for case in cases:
            if not case.current_step_id or not case.current_assignee_id or case.is_locked:
                raise CommandError(
                    f"WorkflowCase #{case.pk} cannot be upgraded: current owner/step is missing or locked."
                )
            target_step = definition.steps.filter(code=case.current_step.code).first()
            if target_step is None:
                raise CommandError(
                    f"WorkflowCase #{case.pk} cannot be upgraded: step '{case.current_step.code}' is absent in v{definition.version}."
                )
            scope = _scope_for_object(case.content_object)
            try:
                position_assignment = _validate_recipient(
                    case.current_assignee,
                    target_step.allowed_roles,
                    position_levels=target_step.allowed_position_levels,
                    scope=scope,
                    source_user=case.current_assignee,
                )
            except (PermissionDenied, ValidationError) as exc:
                if case.delegation_id and is_delegated_assignee(case, case.current_assignee):
                    position_assignment = None
                else:
                    raise CommandError(
                        f"WorkflowCase #{case.pk} owner is not eligible for upgraded step '{target_step.code}': {exc}"
                    ) from exc

            old_definition = case.definition
            old_step = case.current_step
            old_assignee = case.current_assignee
            old_position_assignment = case.current_position_assignment
            case.definition = definition
            case.current_step = target_step
            case.current_position_assignment = position_assignment
            case.save(update_fields=[
                "definition", "current_step", "current_position_assignment",
            ])
            WorkflowEvent.objects.create(
                workflow_case=case,
                actor=actor,
                event_type=WorkflowEvent.EventType.ACTION,
                action_code="workflow_version_migrated",
                from_step=old_step,
                to_step=target_step,
                from_assignee=old_assignee,
                to_assignee=old_assignee,
                from_position_assignment=old_position_assignment,
                to_position_assignment=position_assignment,
                note=(
                    f"انتقال کنترل‌شده پرونده از نسخه {old_definition.version} "
                    f"به نسخه {definition.version} گردش‌کار؛ تاریخچه قبلی حفظ شد."
                ),
                acted_at=timezone.now(),
                sent_at=timezone.now(),
                metadata={
                    "from_version": old_definition.version,
                    "to_version": definition.version,
                },
            )

    def _build_service_request(self, definition, global_roles):
        company_roles = [RoleAssignment.Role.SUBSIDIARY_REP]
        insurer_roles = [RoleAssignment.Role.INSURER_REP]
        employee_roles = [RoleAssignment.Role.INSURED_PERSON]
        review_roles = global_roles + [RoleAssignment.Role.INSURANCE_SPECIALIST]

        steps = {}
        step_specs = (
            (ServiceRequest.Status.SUBMITTED, "ثبت‌شده", company_roles, True, False),
            (ServiceRequest.Status.IN_REVIEW, "در حال بررسی", review_roles, False, False),
            (ServiceRequest.Status.NEEDS_INFO, "نیازمند تکمیل اطلاعات", employee_roles, False, False),
            (ServiceRequest.Status.REFERRED, "ارجاع‌شده به بیمه‌گر", insurer_roles, False, False),
            (ServiceRequest.Status.APPROVED, "تأییدشده", global_roles, False, False),
            (ServiceRequest.Status.REJECTED, "ردشده", global_roles, False, False),
            (ServiceRequest.Status.COMPLETED, "انجام‌شده", global_roles, False, False),
            (ServiceRequest.Status.CLOSED, "بسته‌شده", global_roles, False, True),
        )
        for order, (code, title, roles, initial, terminal) in enumerate(step_specs, start=1):
            steps[code] = WorkflowStep.objects.create(
                definition=definition,
                code=code,
                title=title,
                order=order,
                allowed_roles=roles,
                is_initial=initial,
                is_terminal=terminal,
                allow_return=not terminal,
            )

        def transition(source, target, action, title, allowed, recipients, *, note=False, closes=False):
            WorkflowTransition.objects.create(
                definition=definition,
                source_step=steps[source],
                target_step=None if closes else steps[target],
                action_code=action,
                title=title,
                allowed_roles=allowed,
                recipient_roles=[] if closes else recipients,
                requires_note=note,
                closes_case=closes,
            )

        transition(
            ServiceRequest.Status.SUBMITTED, ServiceRequest.Status.IN_REVIEW,
            "accept_for_review", "پذیرش و ارجاع به کارشناس اداره بیمه",
            company_roles + global_roles, review_roles,
        )
        transition(
            ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.NEEDS_INFO,
            "request_information", "درخواست تکمیل اطلاعات",
            review_roles, employee_roles, note=True,
        )
        transition(
            ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.REFERRED,
            "refer_to_insurer", "ارجاع به بیمه‌گر",
            review_roles, insurer_roles, note=True,
        )
        transition(
            ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.APPROVED,
            "approve", "تأیید درخواست",
            global_roles, global_roles,
        )
        transition(
            ServiceRequest.Status.IN_REVIEW, ServiceRequest.Status.REJECTED,
            "reject", "رد درخواست",
            global_roles, global_roles, note=True,
        )
        transition(
            ServiceRequest.Status.NEEDS_INFO, ServiceRequest.Status.IN_REVIEW,
            "submit_information", "ارسال اطلاعات تکمیلی به مسئول قبلی",
            employee_roles, review_roles, note=True,
        )
        transition(
            ServiceRequest.Status.REFERRED, ServiceRequest.Status.IN_REVIEW,
            "return_from_insurer", "بازگشت پاسخ بیمه‌گر به مسئول قبلی",
            insurer_roles, review_roles, note=True,
        )
        transition(
            ServiceRequest.Status.APPROVED, ServiceRequest.Status.COMPLETED,
            "mark_completed", "ثبت انجام درخواست",
            global_roles, global_roles,
        )
        transition(
            ServiceRequest.Status.REJECTED, None,
            "finalize_rejection", "ثبت نهایی رد",
            global_roles, [], closes=True,
        )
        transition(
            ServiceRequest.Status.COMPLETED, None,
            "finalize_completion", "بستن نهایی درخواست",
            global_roles, [], closes=True,
        )

    def _build_global_approval(self, definition, approved_step_code, roles):
        pending = WorkflowStep.objects.create(
            definition=definition,
            code="pending_approval",
            title="در انتظار تأیید",
            order=1,
            allowed_roles=roles,
            is_initial=True,
            sla_minutes=0,
        )
        approved = WorkflowStep.objects.create(
            definition=definition,
            code=approved_step_code,
            title="تأیید نهایی",
            order=2,
            allowed_roles=roles,
            allow_return=False,
        )
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code="rejected",
            title="رد درخواست",
            order=3,
            allowed_roles=roles,
            allow_return=False,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=pending,
            target_step=approved,
            action_code="approve",
            title="تأیید",
            allowed_roles=roles,
            recipient_roles=roles,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=pending,
            target_step=rejected,
            action_code="reject",
            title="رد",
            allowed_roles=roles,
            recipient_roles=roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=approved,
            action_code="finalize",
            title="ثبت نهایی تأیید",
            allowed_roles=roles,
            closes_case=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=rejected,
            action_code="finalize-rejection",
            title="ثبت نهایی رد",
            allowed_roles=roles,
            closes_case=True,
        )

    def _build_person_change(self, definition):
        company_roles = [RoleAssignment.Role.SUBSIDIARY_REP]
        insurer_roles = [RoleAssignment.Role.INSURER_REP]
        company_review = WorkflowStep.objects.create(
            definition=definition,
            code="company_review",
            title="بررسی اولیه نماینده شرکت",
            order=1,
            allowed_roles=company_roles,
            is_initial=True,
        )
        insurer_update = WorkflowStep.objects.create(
            definition=definition,
            code="insurer_update",
            title="اقدام کارشناس بیمه‌گر",
            order=2,
            allowed_roles=insurer_roles,
        )
        company_final_review = WorkflowStep.objects.create(
            definition=definition,
            code="company_final_review",
            title="بازبینی نهایی نماینده شرکت",
            order=3,
            allowed_roles=company_roles,
        )
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code="rejected",
            title="رد درخواست",
            order=4,
            allowed_roles=company_roles,
            allow_return=False,
        )

        WorkflowTransition.objects.create(
            definition=definition,
            source_step=company_review,
            target_step=insurer_update,
            action_code="refer_to_insurer",
            title="ارجاع به کارشناس بیمه‌گر",
            allowed_roles=company_roles,
            recipient_roles=insurer_roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=company_review,
            target_step=rejected,
            action_code="reject_initial",
            title="رد درخواست",
            allowed_roles=company_roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=insurer_update,
            target_step=company_final_review,
            action_code="return_to_company",
            title="بازگشت برای تأیید نهایی شرکت",
            allowed_roles=insurer_roles,
            recipient_roles=company_roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=insurer_update,
            target_step=company_review,
            action_code="return_for_correction",
            title="بازگشت برای تکمیل اطلاعات",
            allowed_roles=insurer_roles,
            recipient_roles=company_roles,
            requires_note=True,
            is_return=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=company_final_review,
            action_code="approve_and_close",
            title="تأیید نهایی و اعمال اطلاعات",
            allowed_roles=company_roles,
            closes_case=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=company_final_review,
            target_step=insurer_update,
            action_code="send_back_to_insurer",
            title="بازگشت به بیمه‌گر برای اصلاح",
            allowed_roles=company_roles,
            recipient_roles=insurer_roles,
            requires_note=True,
            is_return=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=company_final_review,
            target_step=rejected,
            action_code="reject_final",
            title="رد درخواست پس از بازبینی",
            allowed_roles=company_roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=rejected,
            action_code="close_rejected",
            title="ثبت نهایی رد",
            allowed_roles=company_roles,
            closes_case=True,
        )


    def _build_claim_review(self, definition, global_roles):
        specialist_roles = [RoleAssignment.Role.INSURANCE_SPECIALIST]
        intake_roles = specialist_roles + global_roles
        under_review = WorkflowStep.objects.create(
            definition=definition,
            code="under_review",
            title="ارزیابی تخصصی خسارت",
            order=1,
            allowed_roles=intake_roles,
            is_initial=True,
        )
        needs_info = WorkflowStep.objects.create(
            definition=definition,
            code="needs_info",
            title="نیازمند تکمیل اطلاعات",
            order=2,
            allowed_roles=intake_roles,
        )
        pending_decision = WorkflowStep.objects.create(
            definition=definition,
            code="pending_decision",
            title="در انتظار تصمیم رئیس اداره",
            order=3,
            allowed_roles=global_roles,
        )
        approved = WorkflowStep.objects.create(
            definition=definition,
            code="approved",
            title="تأیید نهایی",
            order=4,
            allowed_roles=global_roles,
            allow_return=False,
        )
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code="rejected",
            title="رد نهایی",
            order=5,
            allowed_roles=global_roles,
            allow_return=False,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=under_review, target_step=needs_info,
            action_code="request_information", title="درخواست تکمیل اطلاعات",
            allowed_roles=intake_roles, recipient_roles=intake_roles, requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=under_review, target_step=pending_decision,
            action_code="submit_for_decision", title="ارسال برای تصمیم نهایی",
            allowed_roles=intake_roles, recipient_roles=global_roles, requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=needs_info, target_step=under_review,
            action_code="resume_review", title="ادامه ارزیابی",
            allowed_roles=intake_roles, recipient_roles=intake_roles,
            requires_note=True, is_return=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=pending_decision, target_step=approved,
            action_code="approve", title="تأیید خسارت",
            allowed_roles=global_roles, recipient_roles=global_roles,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=pending_decision, target_step=rejected,
            action_code="reject", title="رد خسارت",
            allowed_roles=global_roles, recipient_roles=global_roles, requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=approved,
            action_code="finalize", title="ثبت نهایی تأیید",
            allowed_roles=global_roles, closes_case=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=rejected,
            action_code="finalize-rejection", title="ثبت نهایی رد",
            allowed_roles=global_roles, closes_case=True,
        )

    def _build_claim_objection(self, definition, global_roles):
        reviewer_roles = [RoleAssignment.Role.INSURANCE_SPECIALIST] + global_roles
        in_review = WorkflowStep.objects.create(
            definition=definition,
            code="in_review",
            title="در حال بررسی اعتراض",
            order=1,
            allowed_roles=reviewer_roles,
            is_initial=True,
        )
        answered = WorkflowStep.objects.create(
            definition=definition,
            code="answered",
            title="پاسخ داده‌شده",
            order=2,
            allowed_roles=reviewer_roles,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=in_review, target_step=answered,
            action_code="answer", title="ثبت پاسخ اعتراض",
            allowed_roles=reviewer_roles, recipient_roles=reviewer_roles, requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=answered, target_step=in_review,
            action_code="reopen_review", title="بازگشت به بررسی",
            allowed_roles=reviewer_roles, recipient_roles=reviewer_roles,
            requires_note=True, is_return=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=answered,
            action_code="close_objection", title="بستن نهایی اعتراض",
            allowed_roles=global_roles, closes_case=True,
        )
