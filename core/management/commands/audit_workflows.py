from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from accounts.models import OrganizationalPosition, RoleAssignment
from assets.models import AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation
from claims.models import Claim, ClaimObjection
from insurance.models import ContractRevision
from organizations.models import PersonChangeRequest
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowDefinition
from reports.models import Report


class Command(BaseCommand):
    help = "ممیزی کاتالوگ فعال یا ممیزی دامنه‌ای یک پیش‌نویس پیش از تأیید رئیس اداره بیمه."

    DOMAIN_CODES = {
        "claim_review",
        "claim_objection",
        "contract_approval",
        "contract_termination",
        "person_change",
        "asset_valuation_approval",
        "asset_policy_approval",
        "asset_endorsement_approval",
        "management_report_approval",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--definition-id",
            type=int,
            help="Audit one draft proposal before Department Head approval instead of the active catalog.",
        )

    def handle(self, *args, **options):
        required_codes = set(ServiceRequest.Kind.values) | self.DOMAIN_CODES
        proposal_mode = bool(options.get("definition_id"))
        if proposal_mode:
            definition = WorkflowDefinition.objects.filter(
                pk=options["definition_id"]
            ).prefetch_related(
                "steps__outgoing_transitions",
                "transitions__source_step",
                "transitions__target_step",
            ).first()
            if definition is None:
                raise CommandError("تعریف گردش‌کار موردنظر پیدا نشد.")
            if definition.code not in required_codes:
                raise CommandError("کد این تعریف در کاتالوگ ۱۹ فرآیند عملیاتی ثبت نشده است.")
            active_definitions = [definition]
        else:
            active_definitions = list(
                WorkflowDefinition.objects.filter(
                    code__in=required_codes,
                    is_active=True,
                ).prefetch_related("steps__outgoing_transitions", "transitions__source_step", "transitions__target_step")
            )
        definitions = {}
        errors = []
        warnings = []
        for definition in active_definitions:
            if definition.code in definitions:
                errors.append(f"{definition.code}: بیش از یک نسخه فعال گردش‌کار وجود دارد.")
            definitions[definition.code] = definition

        missing = [] if proposal_mode else sorted(required_codes - set(definitions))
        if missing:
            errors.append("گردش‌کار فعال برای این فرآیندها تعریف نشده است: " + ", ".join(missing))

        global_roles = {
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.SYSTEM_ADMIN,
        }
        company_approver_roles = global_roles | {RoleAssignment.Role.SUBSIDIARY_REP}
        insurer_role = RoleAssignment.Role.INSURER_REP
        specialist_role = RoleAssignment.Role.INSURANCE_SPECIALIST

        today = timezone.localdate()
        for code, definition in sorted(definitions.items()):
            if proposal_mode:
                if definition.is_active or definition.published_at or definition.approved_by_id:
                    errors.append(f"{code}: پیشنهاد باید پیش‌نویس و فاقد تأیید/انتشار باشد.")
            elif not definition.published_at:
                errors.append(f"{code}: تعریف فعال فاقد زمان انتشار معتبر است.")
            if definition.created_by_id == definition.approved_by_id:
                errors.append(f"{code}: ایجادکننده و تأییدکننده گردش کار نباید یک نفر باشند.")
            if not RoleAssignment.objects.filter(
                user_id=definition.created_by_id, role=RoleAssignment.Role.SYSTEM_ADMIN,
                is_active=True, valid_from__lte=today,
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).exists():
                errors.append(f"{code}: ایجادکننده نسخه فعال باید مدیر سامانه با انتصاب معتبر باشد.")
            if not proposal_mode and not RoleAssignment.objects.filter(
                user_id=definition.approved_by_id, role=RoleAssignment.Role.DEPARTMENT_HEAD,
                is_active=True, valid_from__lte=today,
            ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today)).exists():
                errors.append(f"{code}: تأییدکننده نسخه فعال باید رئیس اداره بیمه با انتصاب معتبر باشد.")
            steps = list(definition.steps.all())
            transitions = list(definition.transitions.select_related("source_step", "target_step"))
            initial_steps = [step for step in steps if step.is_initial]
            if len(initial_steps) != 1:
                errors.append(f"{code}: باید دقیقاً یک مرحله آغازین داشته باشد.")

            valid_statuses, decision_steps = self._domain_contract(code)
            for step in steps:
                if not step.is_terminal and (
                    step.sla_minutes <= 0
                    or not step.sla_confirmed_by_id
                    or not step.sla_confirmed_at
                ):
                    warnings.append(
                        f"{code}/{step.code}: مهلت نمونه {step.sla_minutes} دقیقه است؛ "
                        "تعیین و تأیید رئیس اداره بیمه الزامی است."
                    )
                if step.is_terminal and step.outgoing_transitions.exists():
                    errors.append(f"{code}/{step.code}: مرحله پایانی نباید مسیر خروجی داشته باشد.")
                if step.code not in valid_statuses:
                    errors.append(f"{code}/{step.code}: کد مرحله با وضعیت مدل دامنه سازگار نیست.")
                if not step.allowed_roles and not step.allowed_position_levels:
                    errors.append(f"{code}/{step.code}: نقش و سمت مجاز مرحله هر دو خالی هستند.")
                if "*" in (step.allowed_roles or []):
                    errors.append(f"{code}/{step.code}: نقش عمومی * مجاز نیست.")
                if not step.is_terminal and not step.outgoing_transitions.exists():
                    errors.append(f"{code}/{step.code}: مرحله غیرپایانی مسیر خروجی ندارد.")

            if len(initial_steps) == 1:
                reachable_ids = {initial_steps[0].pk}
                changed = True
                while changed:
                    changed = False
                    for transition in transitions:
                        if (
                            transition.source_step_id in reachable_ids
                            and transition.target_step_id
                            and transition.target_step_id not in reachable_ids
                        ):
                            reachable_ids.add(transition.target_step_id)
                            changed = True
                for step in steps:
                    if step.pk not in reachable_ids:
                        errors.append(f"{code}/{step.code}: مرحله از مرحله آغازین قابل دسترسی نیست.")

            for transition in transitions:
                if transition.source_step_id not in {step.pk for step in steps}:
                    errors.append(f"{code}/{transition.action_code}: مرحله مبدأ خارج از تعریف است.")
                if transition.target_step_id and transition.target_step_id not in {
                    step.pk for step in steps
                }:
                    errors.append(f"{code}/{transition.action_code}: مرحله مقصد خارج از تعریف است.")
                if transition.closes_case and insurer_role in (transition.allowed_roles or []):
                    errors.append(f"{code}/{transition.action_code}: نماینده بیمه‌گر نباید پرونده را نهایی ببندد.")
                if "*" in (transition.allowed_roles or []) or "*" in (transition.recipient_roles or []):
                    errors.append(f"{code}/{transition.action_code}: نقش عمومی * مجاز نیست.")
                if not transition.closes_case and not (
                    transition.recipient_roles
                    or transition.recipient_position_levels
                    or (
                        transition.target_step
                        and (
                            transition.target_step.allowed_roles
                            or transition.target_step.allowed_position_levels
                        )
                    )
                ):
                    errors.append(f"{code}/{transition.action_code}: نقش گیرنده مسیر مشخص نیست.")

                if code in self.DOMAIN_CODES - {"person_change"} and transition.closes_case:
                    closing_roles = set(
                        transition.allowed_roles or transition.source_step.allowed_roles
                    )
                    closing_positions = set(
                        transition.allowed_position_levels
                        or transition.source_step.allowed_position_levels
                    )
                    if (
                        (not closing_roles and not closing_positions)
                        or not closing_roles.issubset(global_roles)
                        or closing_positions
                    ):
                        errors.append(
                            f"{code}/{transition.action_code}: بستن نهایی فقط برای رئیس اداره/مدیر سامانه مجاز است."
                        )

            for decision_code in decision_steps:
                decision_step = next((step for step in steps if step.code == decision_code), None)
                if decision_step is None:
                    errors.append(f"{code}: مرحله تصمیم نهایی {decision_code} تعریف نشده است.")
                    continue
                if not any(item.closes_case for item in decision_step.outgoing_transitions.all()):
                    errors.append(f"{code}/{decision_code}: تصمیم نهایی باید مسیر بستن پرونده داشته باشد.")
                if not any(item.target_step_id == decision_step.pk for item in transitions):
                    errors.append(f"{code}/{decision_code}: مرحله تصمیم نهایی از مسیر گردش‌کار قابل دسترسی نیست.")

            if code in {"contract_approval", "contract_termination"} and initial_steps:
                if initial_steps[0].code != ContractRevision.Status.PENDING_APPROVAL:
                    errors.append(f"{code}: مرحله آغازین باید pending_approval باشد.")
                initial_roles = set(initial_steps[0].allowed_roles or [])
                if (
                    not initial_roles
                    or not initial_roles.issubset(global_roles)
                    or initial_steps[0].allowed_position_levels
                ):
                    errors.append(f"{code}: مرحله آغازین فقط باید به رئیس اداره/مدیر سامانه واگذار شود.")

            if code in {
                "asset_valuation_approval",
                "asset_policy_approval",
                "asset_endorsement_approval",
            } and initial_steps:
                if initial_steps[0].code != "pending_approval":
                    errors.append(f"{code}: مرحله آغازین باید pending_approval باشد.")
                initial_roles = set(initial_steps[0].allowed_roles or [])
                if (
                    not initial_roles
                    or not initial_roles.issubset(global_roles)
                    or initial_steps[0].allowed_position_levels
                ):
                    errors.append(f"{code}: تأیید دارایی فقط باید به رئیس اداره/مدیر سامانه واگذار شود.")

            if code in set(ServiceRequest.Kind.values):
                company_roles = {RoleAssignment.Role.SUBSIDIARY_REP}
                employee_roles = {RoleAssignment.Role.INSURED_PERSON}
                review_roles = {specialist_role} | global_roles
                required_routes = {
                    "accept_for_review": (
                        ServiceRequest.Status.SUBMITTED,
                        ServiceRequest.Status.IN_REVIEW,
                        company_roles | global_roles,
                        review_roles,
                        False,
                    ),
                    "request_information": (
                        ServiceRequest.Status.IN_REVIEW,
                        ServiceRequest.Status.NEEDS_INFO,
                        review_roles,
                        employee_roles,
                        False,
                    ),
                    "refer_to_insurer": (
                        ServiceRequest.Status.IN_REVIEW,
                        ServiceRequest.Status.REFERRED,
                        review_roles,
                        {insurer_role},
                        False,
                    ),
                    "submit_information": (
                        ServiceRequest.Status.NEEDS_INFO,
                        ServiceRequest.Status.IN_REVIEW,
                        employee_roles,
                        review_roles,
                        False,
                    ),
                    "return_from_insurer": (
                        ServiceRequest.Status.REFERRED,
                        ServiceRequest.Status.IN_REVIEW,
                        {insurer_role},
                        review_roles,
                        False,
                    ),
                    "approve": (
                        ServiceRequest.Status.IN_REVIEW,
                        ServiceRequest.Status.APPROVED,
                        global_roles,
                        global_roles,
                        False,
                    ),
                    "reject": (
                        ServiceRequest.Status.IN_REVIEW,
                        ServiceRequest.Status.REJECTED,
                        global_roles,
                        global_roles,
                        False,
                    ),
                    "mark_completed": (
                        ServiceRequest.Status.APPROVED,
                        ServiceRequest.Status.COMPLETED,
                        global_roles,
                        global_roles,
                        False,
                    ),
                    "finalize_rejection": (
                        ServiceRequest.Status.REJECTED,
                        None,
                        global_roles,
                        set(),
                        True,
                    ),
                    "finalize_completion": (
                        ServiceRequest.Status.COMPLETED,
                        None,
                        global_roles,
                        set(),
                        True,
                    ),
                }
                transitions_by_action = {}
                for transition in transitions:
                    transitions_by_action.setdefault(transition.action_code, []).append(transition)

                for action_code, (
                    expected_source,
                    expected_target,
                    actor_roles,
                    recipient_roles,
                    closes_case,
                ) in required_routes.items():
                    matches = transitions_by_action.get(action_code, [])
                    if len(matches) != 1:
                        errors.append(
                            f"{code}: اقدام ضروری {action_code} باید دقیقاً یک‌بار تعریف شود."
                        )
                        continue

                    transition = matches[0]
                    if transition.source_step.code != expected_source:
                        errors.append(
                            f"{code}/{action_code}: مرحله مبدأ باید {expected_source} باشد."
                        )
                    actual_target = (
                        transition.target_step.code if transition.target_step else None
                    )
                    if actual_target != expected_target or transition.closes_case != closes_case:
                        errors.append(
                            f"{code}/{action_code}: مرحله مقصد یا قاعده بستن با مسیر مصوب منطبق نیست."
                        )
                    if set(transition.allowed_roles or []) != actor_roles:
                        errors.append(
                            f"{code}/{action_code}: نقش‌های اقدام باید دقیقاً با نقش‌های مصوب منطبق باشند."
                        )
                    if transition.allowed_position_levels:
                        errors.append(
                            f"{code}/{action_code}: مجوز سمت‌محور برای اقدام نقش‌محور مجاز نیست."
                        )
                    if set(transition.recipient_roles or []) != recipient_roles:
                        errors.append(
                            f"{code}/{action_code}: نقش‌های گیرنده باید دقیقاً با نقش‌های مصوب منطبق باشند."
                        )
                    if transition.recipient_position_levels:
                        errors.append(
                            f"{code}/{action_code}: گیرنده سمت‌محور برای این مسیر نقش‌محور مجاز نیست."
                        )

                    if expected_target is not None:
                        target_step = transition.target_step
                        if target_step is None:
                            errors.append(
                                f"{code}/{action_code}: مرحله مقصد مصوب تعریف نشده است."
                            )
                        else:
                            if set(target_step.allowed_roles or []) != recipient_roles:
                                errors.append(
                                    f"{code}/{action_code}: نقش‌های مرحله مقصد باید دقیقاً با نقش گیرنده منطبق باشند."
                                )
                            if target_step.allowed_position_levels:
                                errors.append(
                                    f"{code}/{action_code}: مرحله مقصد نباید مجوز سمت‌محور اضافی داشته باشد."
                                )

                unexpected_actions = set(transitions_by_action) - set(required_routes)
                if unexpected_actions:
                    errors.append(
                        f"{code}: اقدام‌های خارج از قرارداد گردش‌کار درخواست عمومی مجاز نیستند: "
                        + ", ".join(sorted(unexpected_actions))
                    )

                required_steps = {
                    ServiceRequest.Status.SUBMITTED: company_roles,
                    ServiceRequest.Status.IN_REVIEW: review_roles,
                    ServiceRequest.Status.NEEDS_INFO: employee_roles,
                    ServiceRequest.Status.REFERRED: {insurer_role},
                    ServiceRequest.Status.APPROVED: global_roles,
                    ServiceRequest.Status.REJECTED: global_roles,
                    ServiceRequest.Status.COMPLETED: global_roles,
                }
                for step_code, expected_roles in required_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if (
                        not step
                        or set(step.allowed_roles or []) != expected_roles
                        or step.allowed_position_levels
                    ):
                        errors.append(
                            f"{code}/{step_code}: نقش‌های مرحله باید دقیقاً با ماتریس مصوب منطبق باشند و مجوز سمت‌محور نداشته باشند."
                        )
                if not initial_steps or initial_steps[0].code != ServiceRequest.Status.SUBMITTED:
                    errors.append(
                        f"{code}: مرحله آغازین درخواست عمومی باید submitted باشد."
                    )

            if code == "management_report_approval":
                supervisor_level = int(OrganizationalPosition.Level.SUPERVISOR)
                responsible_level = int(OrganizationalPosition.Level.RESPONSIBLE)
                required_steps = {
                    "supervisor_review": (set(), {supervisor_level}),
                    "responsible_review": (set(), {responsible_level}),
                    "head_review": (global_roles, set()),
                    "returned": ({specialist_role}, set()),
                    "approved": (global_roles, set()),
                    "rejected": (global_roles, set()),
                }
                for step_code, (expected_roles, expected_levels) in required_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if (
                        not step
                        or set(step.allowed_roles or []) != expected_roles
                        or set(step.allowed_position_levels or []) != expected_levels
                    ):
                        errors.append(
                            f"{code}/{step_code}: نقش‌ها و سطوح سمت باید دقیقاً با قرارداد مصوب منطبق باشند."
                        )
                if not initial_steps or initial_steps[0].code != "supervisor_review":
                    errors.append(f"{code}: مرحله آغازین باید supervisor_review باشد.")

                required_routes = {
                    "approve_to_responsible": [
                        ("supervisor_review", "responsible_review", set(), {supervisor_level},
                         set(), {responsible_level}, False, False, False),
                    ],
                    "return_to_creator": [
                        ("supervisor_review", "returned", set(), {supervisor_level},
                         {specialist_role}, set(), False, True, True),
                        ("responsible_review", "returned", set(), {responsible_level},
                         {specialist_role}, set(), False, True, True),
                    ],
                    "approve_to_head": [
                        ("responsible_review", "head_review", set(), {responsible_level},
                         global_roles, set(), False, False, False),
                    ],
                    "approve": [
                        ("head_review", "approved", global_roles, set(),
                         global_roles, set(), False, False, False),
                    ],
                    "reject": [
                        ("head_review", "rejected", global_roles, set(),
                         global_roles, set(), False, False, True),
                    ],
                    "resubmit": [
                        ("returned", "supervisor_review", {specialist_role}, set(),
                         set(), {supervisor_level}, False, False, False),
                    ],
                    "finalize": [
                        ("approved", None, global_roles, set(), set(), set(), True, False, False),
                    ],
                    "finalize_rejection": [
                        ("rejected", None, global_roles, set(), set(), set(), True, False, False),
                    ],
                }
                transitions_by_action = {}
                for transition in transitions:
                    transitions_by_action.setdefault(transition.action_code, []).append(transition)

                for action_code, expected_routes in required_routes.items():
                    matches = transitions_by_action.get(action_code, [])
                    if len(matches) != len(expected_routes):
                        errors.append(
                            f"{code}/{action_code}: تعداد مسیرها با قرارداد مصوب منطبق نیست."
                        )
                        continue
                    for transition, expected in zip(matches, expected_routes):
                        (
                            source, target, actors, actor_levels, recipients,
                            recipient_levels, closes, is_return, requires_note,
                        ) = expected
                        actual_target = transition.target_step.code if transition.target_step else None
                        if transition.source_step.code != source or actual_target != target:
                            errors.append(f"{code}/{action_code}: مبدأ یا مقصد مسیر غیرمجاز است.")
                        if (
                            set(transition.allowed_roles or []) != actors
                            or set(transition.allowed_position_levels or []) != actor_levels
                        ):
                            errors.append(f"{code}/{action_code}: مجوز اقدام با قرارداد مصوب منطبق نیست.")
                        if (
                            set(transition.recipient_roles or []) != recipients
                            or set(transition.recipient_position_levels or []) != recipient_levels
                        ):
                            errors.append(f"{code}/{action_code}: مجوز گیرنده با قرارداد مصوب منطبق نیست.")
                        if (
                            transition.closes_case != closes
                            or transition.is_return != is_return
                            or transition.requires_note != requires_note
                        ):
                            errors.append(f"{code}/{action_code}: قواعد بستن/بازگشت/یادداشت غیرمجاز است.")
                        if transition.target_step and (
                            set(transition.target_step.allowed_roles or []) != recipients
                            or set(transition.target_step.allowed_position_levels or []) != recipient_levels
                        ):
                            errors.append(f"{code}/{action_code}: مجوزهای مرحله مقصد غیرمجاز است.")

                unexpected_actions = set(transitions_by_action) - set(required_routes)
                if unexpected_actions:
                    errors.append(
                        f"{code}: اقدام‌های خارج از قرارداد مجاز نیستند: "
                        + ", ".join(sorted(unexpected_actions))
                    )

            if code == "claim_review":
                intake_roles = {specialist_role} | global_roles
                required_steps = {
                    Claim.Status.UNDER_REVIEW: intake_roles,
                    Claim.Status.NEEDS_INFO: intake_roles,
                    "pending_decision": global_roles,
                    Claim.Status.APPROVED: global_roles,
                    Claim.Status.REJECTED: global_roles,
                }
                for step_code, expected_roles in required_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if (
                        not step
                        or set(step.allowed_roles or []) != expected_roles
                        or step.allowed_position_levels
                    ):
                        errors.append(
                            f"claim_review/{step_code}: نقش مرحله باید دقیقاً با قرارداد مصوب منطبق باشد."
                        )
                if not initial_steps or initial_steps[0].code != Claim.Status.UNDER_REVIEW:
                    errors.append("claim_review: مرحله آغازین باید under_review باشد.")

                required_routes = {
                    "request_information": (
                        Claim.Status.UNDER_REVIEW, Claim.Status.NEEDS_INFO,
                        intake_roles, intake_roles, False, False,
                    ),
                    "submit_for_decision": (
                        Claim.Status.UNDER_REVIEW, "pending_decision",
                        intake_roles, global_roles, False, False,
                    ),
                    "resume_review": (
                        Claim.Status.NEEDS_INFO, Claim.Status.UNDER_REVIEW,
                        intake_roles, intake_roles, False, True,
                    ),
                    "approve": (
                        "pending_decision", Claim.Status.APPROVED,
                        global_roles, global_roles, False, False,
                    ),
                    "reject": (
                        "pending_decision", Claim.Status.REJECTED,
                        global_roles, global_roles, False, False,
                    ),
                    "finalize": (
                        Claim.Status.APPROVED, None,
                        global_roles, set(), True, False,
                    ),
                    "finalize-rejection": (
                        Claim.Status.REJECTED, None,
                        global_roles, set(), True, False,
                    ),
                }
                transitions_by_action = {}
                for transition in transitions:
                    transitions_by_action.setdefault(transition.action_code, []).append(transition)

                for action_code, expected in required_routes.items():
                    matches = transitions_by_action.get(action_code, [])
                    if len(matches) != 1:
                        errors.append(
                            f"claim_review/{action_code}: اقدام باید دقیقاً یک‌بار تعریف شود."
                        )
                        continue
                    transition = matches[0]
                    source, target, actors, recipients, closes, is_return = expected
                    actual_target = transition.target_step.code if transition.target_step else None
                    if transition.source_step.code != source or actual_target != target:
                        errors.append(
                            f"claim_review/{action_code}: مبدأ یا مقصد با مسیر مصوب منطبق نیست."
                        )
                    if (
                        set(transition.allowed_roles or []) != actors
                        or transition.allowed_position_levels
                    ):
                        errors.append(
                            f"claim_review/{action_code}: نقش یا مجوز سمت‌محور اقدام غیرمجاز است."
                        )
                    if (
                        set(transition.recipient_roles or []) != recipients
                        or transition.recipient_position_levels
                    ):
                        errors.append(
                            f"claim_review/{action_code}: نقش یا مجوز سمت‌محور گیرنده غیرمجاز است."
                        )
                    if transition.closes_case != closes or transition.is_return != is_return:
                        errors.append(
                            f"claim_review/{action_code}: قاعده بستن یا بازگشت با قرارداد مصوب منطبق نیست."
                        )
                    if transition.target_step and (
                        set(transition.target_step.allowed_roles or []) != recipients
                        or transition.target_step.allowed_position_levels
                    ):
                        errors.append(
                            f"claim_review/{action_code}: مجوزهای مرحله مقصد با گیرنده مصوب منطبق نیست."
                        )

                unexpected_actions = set(transitions_by_action) - set(required_routes)
                if unexpected_actions:
                    errors.append(
                        "claim_review: اقدام‌های خارج از قرارداد مجاز نیستند: "
                        + ", ".join(sorted(unexpected_actions))
                    )

            if code == "claim_objection":
                expected_steps = {
                    ClaimObjection.Status.IN_REVIEW: {specialist_role},
                    ClaimObjection.Status.ANSWERED: global_roles,
                }
                for step_code, expected_roles in expected_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if (
                        not step
                        or set(step.allowed_roles or []) != expected_roles
                        or step.allowed_position_levels
                    ):
                        errors.append(
                            f"claim_objection/{step_code}: نقش‌های مرحله باید دقیقاً با ماتریس مصوب منطبق باشند و مجوز سمت‌محور نداشته باشند."
                        )

                if not initial_steps or initial_steps[0].code != ClaimObjection.Status.IN_REVIEW:
                    errors.append("claim_objection: مرحله آغازین باید in_review باشد.")

                required_routes = {
                    "answer": (
                        ClaimObjection.Status.IN_REVIEW,
                        ClaimObjection.Status.ANSWERED,
                        {specialist_role},
                        global_roles,
                        False,
                        False,
                    ),
                    "reopen_review": (
                        ClaimObjection.Status.ANSWERED,
                        ClaimObjection.Status.IN_REVIEW,
                        global_roles,
                        {specialist_role},
                        False,
                        True,
                    ),
                    "close_objection": (
                        ClaimObjection.Status.ANSWERED,
                        None,
                        global_roles,
                        set(),
                        True,
                        False,
                    ),
                }
                transitions_by_action = {}
                for transition in transitions:
                    transitions_by_action.setdefault(transition.action_code, []).append(transition)

                for action_code, (
                    expected_source,
                    expected_target,
                    actor_roles,
                    recipient_roles,
                    closes_case,
                    is_return,
                ) in required_routes.items():
                    matches = transitions_by_action.get(action_code, [])
                    if len(matches) != 1:
                        errors.append(
                            f"claim_objection: اقدام {action_code} باید دقیقاً یک‌بار تعریف شود."
                        )
                        continue

                    transition = matches[0]
                    if transition.source_step.code != expected_source:
                        errors.append(
                            f"claim_objection/{action_code}: مرحله مبدأ باید {expected_source} باشد."
                        )
                    actual_target = (
                        transition.target_step.code if transition.target_step else None
                    )
                    if actual_target != expected_target or transition.closes_case != closes_case:
                        errors.append(
                            f"claim_objection/{action_code}: مرحله مقصد یا قاعده بستن با مسیر مصوب منطبق نیست."
                        )
                    if set(transition.allowed_roles or []) != actor_roles:
                        errors.append(
                            f"claim_objection/{action_code}: نقش‌های اقدام باید دقیقاً با ماتریس مصوب منطبق باشند."
                        )
                    if transition.allowed_position_levels:
                        errors.append(
                            f"claim_objection/{action_code}: مجوز سمت‌محور برای اقدام نقش‌محور مجاز نیست."
                        )
                    if set(transition.recipient_roles or []) != recipient_roles:
                        errors.append(
                            f"claim_objection/{action_code}: نقش‌های گیرنده باید دقیقاً با ماتریس مصوب منطبق باشند."
                        )
                    if transition.recipient_position_levels:
                        errors.append(
                            f"claim_objection/{action_code}: گیرنده سمت‌محور برای این مسیر نقش‌محور مجاز نیست."
                        )
                    if transition.is_return != is_return:
                        errors.append(
                            f"claim_objection/{action_code}: نشانگر ارجاع مجدد با قرارداد مسیر منطبق نیست."
                        )

                    if expected_target is not None:
                        target_step = transition.target_step
                        if target_step is None:
                            errors.append(
                                f"claim_objection/{action_code}: مرحله مقصد مصوب تعریف نشده است."
                            )
                        else:
                            if set(target_step.allowed_roles or []) != recipient_roles:
                                errors.append(
                                    f"claim_objection/{action_code}: نقش‌های مرحله مقصد باید دقیقاً با نقش گیرنده منطبق باشند."
                                )
                            if target_step.allowed_position_levels:
                                errors.append(
                                    f"claim_objection/{action_code}: مرحله مقصد نباید مجوز سمت‌محور اضافی داشته باشد."
                                )

                unexpected_actions = set(transitions_by_action) - set(required_routes)
                if unexpected_actions:
                    errors.append(
                        "claim_objection: اقدام‌های خارج از قرارداد گردش‌کار اعتراض مجاز نیستند: "
                        + ", ".join(sorted(unexpected_actions))
                    )

            if code == "person_change":
                company_role = RoleAssignment.Role.SUBSIDIARY_REP
                required_steps = {
                    PersonChangeRequest.Status.COMPANY_REVIEW: {company_role},
                    PersonChangeRequest.Status.INSURER_UPDATE: {insurer_role},
                    PersonChangeRequest.Status.COMPANY_FINAL_REVIEW: {company_role},
                    PersonChangeRequest.Status.REJECTED: {company_role},
                }
                for step_code, expected_roles in required_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if (
                        not step
                        or set(step.allowed_roles or []) != expected_roles
                        or step.allowed_position_levels
                    ):
                        errors.append(
                            f"person_change/{step_code}: نقش مرحله باید دقیقاً با قرارداد مصوب منطبق باشد."
                        )
                if not initial_steps or initial_steps[0].code != PersonChangeRequest.Status.COMPANY_REVIEW:
                    errors.append("person_change: مرحله آغازین باید company_review باشد.")

                required_routes = {
                    "refer_to_insurer": (
                        PersonChangeRequest.Status.COMPANY_REVIEW,
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        {company_role}, {insurer_role}, False, False,
                    ),
                    "reject_initial": (
                        PersonChangeRequest.Status.COMPANY_REVIEW,
                        PersonChangeRequest.Status.REJECTED,
                        {company_role}, set(), False, False,
                    ),
                    "return_to_company": (
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        {insurer_role}, {company_role}, False, False,
                    ),
                    "return_for_correction": (
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        PersonChangeRequest.Status.COMPANY_REVIEW,
                        {insurer_role}, {company_role}, False, True,
                    ),
                    "approve_and_close": (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        None, {company_role}, set(), True, False,
                    ),
                    "send_back_to_insurer": (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        {company_role}, {insurer_role}, False, True,
                    ),
                    "reject_final": (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.REJECTED,
                        {company_role}, set(), False, False,
                    ),
                    "close_rejected": (
                        PersonChangeRequest.Status.REJECTED,
                        None, {company_role}, set(), True, False,
                    ),
                }
                transitions_by_action = {}
                for transition in transitions:
                    transitions_by_action.setdefault(transition.action_code, []).append(transition)

                for action_code, expected in required_routes.items():
                    matches = transitions_by_action.get(action_code, [])
                    if len(matches) != 1:
                        errors.append(
                            f"person_change/{action_code}: اقدام باید دقیقاً یک‌بار تعریف شود."
                        )
                        continue
                    transition = matches[0]
                    source, target, actors, recipients, closes, is_return = expected
                    actual_target = transition.target_step.code if transition.target_step else None
                    if transition.source_step.code != source or actual_target != target:
                        errors.append(
                            f"person_change/{action_code}: مبدأ یا مقصد با مسیر مصوب منطبق نیست."
                        )
                    if set(transition.allowed_roles or []) != actors or transition.allowed_position_levels:
                        errors.append(
                            f"person_change/{action_code}: نقش یا مجوز سمت‌محور اقدام غیرمجاز است."
                        )
                    if set(transition.recipient_roles or []) != recipients or transition.recipient_position_levels:
                        errors.append(
                            f"person_change/{action_code}: نقش یا مجوز سمت‌محور گیرنده غیرمجاز است."
                        )
                    if transition.closes_case != closes or transition.is_return != is_return:
                        errors.append(
                            f"person_change/{action_code}: قاعده بستن یا بازگشت با قرارداد مصوب منطبق نیست."
                        )
                    if transition.target_step:
                        target_step = transition.target_step
                        if (
                            set(target_step.allowed_roles or []) != recipients
                            or target_step.allowed_position_levels
                        ):
                            errors.append(
                                f"person_change/{action_code}: مجوزهای مرحله مقصد با گیرنده مصوب منطبق نیست."
                            )

                unexpected_actions = set(transitions_by_action) - set(required_routes)
                if unexpected_actions:
                    errors.append(
                        "person_change: اقدام‌های خارج از قرارداد مجاز نیستند: "
                        + ", ".join(sorted(unexpected_actions))
                    )

            for warning in warnings:
            self.stdout.write(self.style.WARNING("هشدار SLA: " + warning))

        if errors:
            for error in errors:
                self.stdout.write(self.style.ERROR(error))
            raise CommandError(
                f"ممیزی گردش‌کار ناموفق بود؛ {len(missing)} فرآیند فاقد گردش‌کار و {len(errors)} مغایرت."
            )

        if proposal_mode:
            self.stdout.write(self.style.SUCCESS(
                f"ممیزی پیشنهاد موفق: گردش‌کار {active_definitions[0].code} از نظر ساختار، نقش‌ها و مسیرهای دامنه معتبر است."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"ممیزی موفق: هر {len(required_codes)} فرآیند دارای گردش‌کار فعال و معتبر است."
            ))

    @staticmethod
    def _domain_contract(code):
        if code == "management_report_approval":
            return set(dict(Report.Status.choices)), {Report.Status.APPROVED, Report.Status.REJECTED}
        if code == "claim_review":
            return set(dict(Claim.Status.choices)), {
                Claim.Status.APPROVED,
                Claim.Status.REJECTED,
            }
        if code == "claim_objection":
            return set(dict(ClaimObjection.Status.choices)), {ClaimObjection.Status.ANSWERED}
        if code in {"contract_approval", "contract_termination"}:
            decisions = (
                {ContractRevision.Status.APPROVED, ContractRevision.Status.REJECTED}
                if code == "contract_approval"
                else {ContractRevision.Status.TERMINATED, ContractRevision.Status.REJECTED}
            )
            return set(dict(ContractRevision.Status.choices)), decisions
        if code == "person_change":
            return set(dict(PersonChangeRequest.Status.choices)), {PersonChangeRequest.Status.REJECTED}
        if code == "asset_valuation_approval":
            return set(dict(AssetValuation.Status.choices)), {
                AssetValuation.Status.APPROVED,
                AssetValuation.Status.REJECTED,
            }
        if code == "asset_policy_approval":
            return set(dict(AssetPolicyPeriod.Status.choices)), {
                AssetPolicyPeriod.Status.APPROVED,
                AssetPolicyPeriod.Status.REJECTED,
            }
        if code == "asset_endorsement_approval":
            return set(dict(AssetPolicyEndorsement.Status.choices)), {
                AssetPolicyEndorsement.Status.APPROVED,
                AssetPolicyEndorsement.Status.REJECTED,
            }
        return set(dict(ServiceRequest.Status.choices)), set()
