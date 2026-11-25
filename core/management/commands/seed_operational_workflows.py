from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Max
from django.utils import timezone

from accounts.models import OrganizationalPosition, RoleAssignment
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowDefinition, WorkflowStep, WorkflowTransition


class Command(BaseCommand):
    help = "Create draft proposals for the 19 operational workflows; publication requires an authenticated Department Head."
    BASELINE_SCHEMA_VERSION = "baseline-route-v4"

    WORKFLOWS = (
        ("contract_approval", "تأیید قرارداد", "approved"),
        ("contract_termination", "تأیید فسخ قرارداد", "terminated"),
        ("asset_valuation_approval", "تأیید ارزیابی دارایی", "approved"),
        ("asset_policy_approval", "تأیید دوره بیمه‌نامه دارایی", "approved"),
        ("asset_endorsement_approval", "تأیید الحاقیه دارایی", "approved"),
        ("person_change", "اصلاح اطلاعات بیمه‌شده", "approved"),
        ("claim_review", "ارزیابی و تصمیم خسارت", "approved"),
        ("claim_objection", "رسیدگی به اعتراض خسارت", "closed"),
        ("management_report_approval", "تأیید سلسله‌مراتبی گزارش مدیریتی", "approved"),
    )

    def add_arguments(self, parser):
        parser.add_argument("--created-by", type=int, required=True)
        parser.add_argument(
            "--commit-proposals",
            action="store_true",
            help="Persist the generated draft proposals. This never approves or publishes them.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        today = timezone.localdate()
        try:
            creator = User.objects.get(pk=options["created_by"], is_active=True)
        except User.DoesNotExist as exc:
            raise CommandError("--created-by must identify an existing active user.") from exc

        creator_assignment = RoleAssignment.objects.filter(
            user=creator,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            is_active=True,
            valid_from__lte=today,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).exists()
        if not creator_assignment:
            raise CommandError("The proposal creator must have an active, time-valid System Admin assignment.")

        operational_catalog = list(self.WORKFLOWS) + [
            (code, f"گردش درخواست: {title}", None)
            for code, title in ServiceRequest.Kind.choices
        ]
        created = []
        skipped = []

        for code, title, approved_step_code in operational_catalog:
            active = WorkflowDefinition.objects.filter(code=code, is_active=True).first()
            if active and self.BASELINE_SCHEMA_VERSION in active.description:
                skipped.append(f"{code} (نسخه پایه از قبل فعال است)")
                continue

            existing_proposal = WorkflowDefinition.objects.filter(
                code=code,
                is_active=False,
                published_at__isnull=True,
                approved_by__isnull=True,
                description__contains=self.BASELINE_SCHEMA_VERSION,
            ).order_by("-version").first()
            if existing_proposal:
                skipped.append(f"{code} (پیشنهاد نسخه {existing_proposal.version} از قبل ثبت شده است)")
                continue

            version = (
                WorkflowDefinition.objects.filter(code=code)
                .aggregate(value=Max("version"))["value"] or 0
            ) + 1
            definition = WorkflowDefinition.objects.create(
                code=code,
                title=title,
                version=version,
                created_by=creator,
                description=(
                    f"{self.BASELINE_SCHEMA_VERSION}: پیش‌نویس پیشنهادی گردش‌کار. "
                    "این نسخه تا زمان تأیید مستقیم رئیس اداره بیمه غیرفعال می‌ماند. "
                    "نسخه فعال قبلی و پرونده‌های جاری آن بدون تغییر حفظ می‌شوند."
                ),
            )
            global_roles = [
                RoleAssignment.Role.DEPARTMENT_HEAD,
                RoleAssignment.Role.SYSTEM_ADMIN,
            ]
            if code == "person_change":
                self._build_person_change(definition)
            elif code == "claim_review":
                self._build_claim_review(definition, global_roles)
            elif code == "claim_objection":
                self._build_claim_objection(definition, global_roles)
            elif code == "management_report_approval":
                self._build_report_approval(definition, global_roles)
            elif approved_step_code:
                self._build_global_approval(definition, approved_step_code, global_roles)
            else:
                self._build_service_request(definition, global_roles)

            if definition.steps.filter(is_initial=True).count() != 1:
                raise CommandError(f"{code}: proposal must contain exactly one initial step.")
            if not definition.transitions.exists():
                raise CommandError(f"{code}: proposal must contain at least one transition.")
            definition.full_clean()
            created.append(f"{code} v{version}")

        if options["commit_proposals"]:
            if created:
                self.stdout.write(self.style.SUCCESS("Draft proposals created: " + ", ".join(created)))
            else:
                self.stdout.write("No new proposals were required.")
        else:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING(
                "DRY RUN: all proposal definitions and routes were validated, then rolled back. "
                "Re-run with --commit-proposals to persist drafts."
            ))

        if skipped:
            self.stdout.write("Unchanged: " + ", ".join(skipped))
        self.stdout.write(
            "No workflow was approved or activated, no existing active version was retired, "
            "and no open case was migrated. A Department Head must approve each proposal "
            "from the authenticated Workflow Governance page."
        )

    def _build_report_approval(self, definition, global_roles):
        specialist_roles = [RoleAssignment.Role.INSURANCE_SPECIALIST]
        supervisor_level = int(OrganizationalPosition.Level.SUPERVISOR)
        responsible_level = int(OrganizationalPosition.Level.RESPONSIBLE)
        specs = (
            ("supervisor_review", "بررسی سرپرست", [], [supervisor_level], True),
            ("responsible_review", "بررسی مسئول", [], [responsible_level], False),
            ("head_review", "بررسی رئیس اداره", global_roles, [], False),
            ("returned", "بازگشت برای اصلاح", specialist_roles, [], False),
            ("approved", "تأیید نهایی", global_roles, [], False),
            ("rejected", "رد گزارش", global_roles, [], False),
        )
        steps = {}
        for order, (code, title, roles, levels, initial) in enumerate(specs, start=1):
            steps[code] = WorkflowStep.objects.create(
                definition=definition, code=code, title=title, order=order,
                allowed_roles=roles, allowed_position_levels=levels,
                is_initial=initial, allow_return=True,
            )

        def add(
            source, target, action, title, roles, recipient_roles=None, *,
            levels=None, recipient_levels=None, note=False, returned=False, closes=False,
        ):
            # JSON routing fields must always be lists. Normalize both
            # empty defaults and explicit iterables before model validation.
            WorkflowTransition.objects.create(
                definition=definition,
                source_step=steps[source],
                target_step=None if closes else steps[target],
                action_code=action,
                title=title,
                allowed_roles=list(roles or []),
                allowed_position_levels=list(levels or []),
                recipient_roles=list(recipient_roles or []),
                recipient_position_levels=list(recipient_levels or []),
                requires_note=note,
                is_return=returned,
                closes_case=closes,
            )

        add("supervisor_review", "responsible_review", "approve_to_responsible", "تأیید سرپرست و ارجاع به مسئول", [], recipient_levels=[responsible_level], levels=[supervisor_level])
        add("supervisor_review", "returned", "return_to_creator", "بازگشت به تهیه‌کننده برای اصلاح", [], specialist_roles, levels=[supervisor_level], note=True, returned=True)
        add("responsible_review", "head_review", "approve_to_head", "تأیید مسئول و ارجاع به رئیس اداره", [], global_roles, levels=[responsible_level])
        add("responsible_review", "returned", "return_to_creator", "بازگشت به تهیه‌کننده برای اصلاح", [], specialist_roles, levels=[responsible_level], note=True, returned=True)
        add("head_review", "approved", "approve", "تأیید نهایی گزارش", global_roles, global_roles)
        add("head_review", "rejected", "reject", "رد گزارش", global_roles, global_roles, note=True)
        add("returned", "supervisor_review", "resubmit", "ارسال نسخه اصلاح‌شده به سرپرست", specialist_roles, recipient_levels=[supervisor_level])
        add("approved", None, "finalize", "مختومه‌سازی گزارش تأییدشده", global_roles, closes=True)
        add("rejected", None, "finalize_rejection", "مختومه‌سازی گزارش ردشده", global_roles, closes=True)

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
        specialist_roles = [RoleAssignment.Role.INSURANCE_SPECIALIST]
        in_review = WorkflowStep.objects.create(
            definition=definition,
            code="in_review",
            title="در حال بررسی اعتراض توسط کارشناس بیمه",
            order=1,
            allowed_roles=specialist_roles,
            is_initial=True,
        )
        answered = WorkflowStep.objects.create(
            definition=definition,
            code="answered",
            title="پاسخ کارشناسی؛ در انتظار تصمیم رئیس اداره",
            order=2,
            allowed_roles=global_roles,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=in_review, target_step=answered,
            action_code="answer", title="ثبت پاسخ کارشناسی اعتراض",
            allowed_roles=specialist_roles, recipient_roles=global_roles, requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=answered, target_step=in_review,
            action_code="reopen_review", title="ارجاع مجدد برای بررسی کارشناسی",
            allowed_roles=global_roles, recipient_roles=specialist_roles,
            requires_note=True, is_return=True,
        )
        WorkflowTransition.objects.create(
            definition=definition, source_step=answered,
            action_code="close_objection", title="بستن نهایی اعتراض",
            allowed_roles=global_roles, closes_case=True,
        )
