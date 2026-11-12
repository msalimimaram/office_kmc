from django.core.management.base import BaseCommand, CommandError

from accounts.models import RoleAssignment
from assets.models import AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation
from claims.models import Claim, ClaimObjection
from insurance.models import ContractRevision
from organizations.models import PersonChangeRequest
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowDefinition


class Command(BaseCommand):
    help = "ممیزی کامل پوشش، نقش‌ها و مسیرهای بستن گردش‌کار پیش از انتشار."

    DOMAIN_CODES = {
        "claim_review",
        "claim_objection",
        "contract_approval",
        "contract_termination",
        "person_change",
        "asset_valuation_approval",
        "asset_policy_approval",
        "asset_endorsement_approval",
    }

    def handle(self, *args, **options):
        required_codes = set(ServiceRequest.Kind.values) | self.DOMAIN_CODES
        active_definitions = list(
            WorkflowDefinition.objects.filter(
                code__in=required_codes,
                is_active=True,
            ).prefetch_related("steps__outgoing_transitions", "transitions__source_step", "transitions__target_step")
        )
        definitions = {}
        errors = []
        for definition in active_definitions:
            if definition.code in definitions:
                errors.append(f"{definition.code}: بیش از یک نسخه فعال گردش‌کار وجود دارد.")
            definitions[definition.code] = definition

        missing = sorted(required_codes - set(definitions))
        if missing:
            errors.append("گردش‌کار فعال برای این فرآیندها تعریف نشده است: " + ", ".join(missing))

        global_roles = {
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.SYSTEM_ADMIN,
        }
        company_approver_roles = global_roles | {RoleAssignment.Role.SUBSIDIARY_REP}
        insurer_role = RoleAssignment.Role.INSURER_REP
        specialist_role = RoleAssignment.Role.INSURANCE_SPECIALIST

        for code, definition in sorted(definitions.items()):
            steps = list(definition.steps.all())
            transitions = list(definition.transitions.select_related("source_step", "target_step"))
            initial_steps = [step for step in steps if step.is_initial]
            if len(initial_steps) != 1:
                errors.append(f"{code}: باید دقیقاً یک مرحله آغازین داشته باشد.")

            valid_statuses, decision_steps = self._domain_contract(code)
            for step in steps:
                if step.code not in valid_statuses:
                    errors.append(f"{code}/{step.code}: کد مرحله با وضعیت مدل دامنه سازگار نیست.")
                if not step.allowed_roles and not step.allowed_position_levels:
                    errors.append(f"{code}/{step.code}: نقش و سمت مجاز مرحله هر دو خالی هستند.")
                if "*" in (step.allowed_roles or []):
                    errors.append(f"{code}/{step.code}: نقش عمومی * مجاز نیست.")
                if not step.is_terminal and not step.outgoing_transitions.exists():
                    errors.append(f"{code}/{step.code}: مرحله غیرپایانی مسیر خروجی ندارد.")

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
                by_action = {item.action_code: item for item in transitions}
                required_routes = {
                    "accept_for_review": (
                        {RoleAssignment.Role.SUBSIDIARY_REP} | global_roles,
                        {specialist_role} | global_roles,
                    ),
                    "request_information": (
                        {specialist_role} | global_roles,
                        {RoleAssignment.Role.INSURED_PERSON},
                    ),
                    "refer_to_insurer": (
                        {specialist_role} | global_roles,
                        {insurer_role},
                    ),
                    "submit_information": (
                        {RoleAssignment.Role.INSURED_PERSON},
                        {specialist_role} | global_roles,
                    ),
                    "return_from_insurer": (
                        {insurer_role},
                        {specialist_role} | global_roles,
                    ),
                }
                for action_code, (actor_roles, recipient_roles) in required_routes.items():
                    transition = by_action.get(action_code)
                    if transition is None:
                        errors.append(f"{code}: اقدام ضروری {action_code} تعریف نشده است.")
                        continue
                    allowed = set(transition.allowed_roles or transition.source_step.allowed_roles)
                    recipients = set(
                        transition.recipient_roles
                        or (transition.target_step.allowed_roles if transition.target_step else [])
                    )
                    if not actor_roles.issubset(allowed):
                        errors.append(f"{code}/{action_code}: نقش اقدام با مسیر کسب‌وکار سازگار نیست.")
                    if not recipient_roles.issubset(recipients):
                        errors.append(f"{code}/{action_code}: گیرنده مرحله بعد با مسیر کسب‌وکار سازگار نیست.")
                submitted = next((step for step in steps if step.code == ServiceRequest.Status.SUBMITTED), None)
                if not submitted or RoleAssignment.Role.SUBSIDIARY_REP not in (submitted.allowed_roles or []):
                    errors.append(f"{code}: مرحله ثبت اولیه باید به نماینده همان شرکت تخصیص یابد.")
                referred = next((step for step in steps if step.code == ServiceRequest.Status.REFERRED), None)
                if not referred or insurer_role not in (referred.allowed_roles or []):
                    errors.append(f"{code}: مرحله ارجاع‌شده باید فقط به نقش بیمه‌گر مجاز باشد.")
                for transition in transitions:
                    if transition.closes_case:
                        closing_roles = set(transition.allowed_roles or transition.source_step.allowed_roles)
                        if not closing_roles or not closing_roles.issubset(global_roles):
                            errors.append(f"{code}/{transition.action_code}: بستن درخواست عمومی فقط برای رئیس اداره/مدیر سامانه مجاز است.")

            if code == "claim_review":
                if not initial_steps or initial_steps[0].code != Claim.Status.UNDER_REVIEW:
                    errors.append("claim_review: مرحله آغازین باید under_review باشد.")
                elif not (
                    specialist_role in (initial_steps[0].allowed_roles or [])
                    or bool(set(initial_steps[0].allowed_roles or []) & global_roles)
                ):
                    errors.append("claim_review: مرحله آغازین باید به کارشناس بیمه یا مرجع سراسری مجاز باشد.")
                submit = next((item for item in transitions if item.action_code == "submit_for_decision"), None)
                if not submit or not (global_roles & set(submit.recipient_roles or [])):
                    errors.append("claim_review: ارجاع تصمیم نهایی باید به رئیس اداره/مدیر سامانه باشد.")

            if code == "claim_objection":
                if not initial_steps or initial_steps[0].code != ClaimObjection.Status.IN_REVIEW:
                    errors.append("claim_objection: مرحله آغازین باید in_review باشد.")
                answer = next((item for item in transitions if item.action_code == "answer"), None)
                close = next((item for item in transitions if item.action_code == "close_objection"), None)
                if not answer or specialist_role not in (answer.allowed_roles or []):
                    errors.append("claim_objection: کارشناس بیمه باید مجاز به ثبت پاسخ باشد.")
                if not close or not close.closes_case or not set(close.allowed_roles or []).issubset(global_roles):
                    errors.append("claim_objection: بستن اعتراض فقط برای رئیس اداره/مدیر سامانه مجاز است.")

            if code == "person_change":
                if not initial_steps or initial_steps[0].code != PersonChangeRequest.Status.COMPANY_REVIEW:
                    errors.append("person_change: مرحله آغازین باید company_review باشد.")
                elif RoleAssignment.Role.SUBSIDIARY_REP not in (initial_steps[0].allowed_roles or []):
                    errors.append("person_change: بررسی اولیه باید به نماینده شرکت واگذار شود.")

                required_steps = {
                    PersonChangeRequest.Status.INSURER_UPDATE: insurer_role,
                    PersonChangeRequest.Status.COMPANY_FINAL_REVIEW: RoleAssignment.Role.SUBSIDIARY_REP,
                    PersonChangeRequest.Status.REJECTED: RoleAssignment.Role.SUBSIDIARY_REP,
                }
                for step_code, role in required_steps.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if not step or role not in (step.allowed_roles or []):
                        errors.append(f"person_change/{step_code}: نقش مجاز ضروری تعریف نشده است.")

                required_edges = {
                    (PersonChangeRequest.Status.COMPANY_REVIEW, PersonChangeRequest.Status.INSURER_UPDATE),
                    (PersonChangeRequest.Status.INSURER_UPDATE, PersonChangeRequest.Status.COMPANY_FINAL_REVIEW),
                    (PersonChangeRequest.Status.COMPANY_FINAL_REVIEW, PersonChangeRequest.Status.REJECTED),
                }
                for source_code, target_code in required_edges:
                    if not any(
                        item.source_step.code == source_code
                        and item.target_step
                        and item.target_step.code == target_code
                        for item in transitions
                    ):
                        errors.append(f"person_change: مسیر {source_code} به {target_code} تعریف نشده است.")

                if not any(
                    item.source_step.code == PersonChangeRequest.Status.COMPANY_FINAL_REVIEW
                    and item.closes_case
                    and RoleAssignment.Role.SUBSIDIARY_REP in (item.allowed_roles or [])
                    for item in transitions
                ):
                    errors.append("person_change: تأیید نهایی و بستن باید توسط نماینده شرکت انجام شود.")

                for transition in transitions:
                    if transition.closes_case and not set(
                        transition.allowed_roles or transition.source_step.allowed_roles
                    ).issubset(company_approver_roles):
                        errors.append(f"person_change/{transition.action_code}: نقش بستن نهایی غیرمجاز است.")

                    source_code = transition.source_step.code
                    target_code = transition.target_step.code if transition.target_step else None
                    if (
                        source_code == PersonChangeRequest.Status.COMPANY_REVIEW
                        and target_code == PersonChangeRequest.Status.INSURER_UPDATE
                        and insurer_role not in (transition.recipient_roles or [])
                    ):
                        errors.append("person_change: ارجاع از شرکت باید به نماینده بیمه‌گر باشد.")
                    if (
                        source_code == PersonChangeRequest.Status.INSURER_UPDATE
                        and target_code == PersonChangeRequest.Status.COMPANY_FINAL_REVIEW
                        and RoleAssignment.Role.SUBSIDIARY_REP not in (transition.recipient_roles or [])
                    ):
                        errors.append("person_change: نتیجه بیمه‌گر باید به نماینده شرکت بازگردد.")

        if errors:
            for error in errors:
                self.stdout.write(self.style.ERROR(error))
            raise CommandError(
                f"ممیزی گردش‌کار ناموفق بود؛ {len(missing)} فرآیند فاقد گردش‌کار و {len(errors)} مغایرت."
            )
        self.stdout.write(self.style.SUCCESS(
            f"ممیزی موفق: هر {len(required_codes)} فرآیند دارای گردش‌کار فعال و معتبر است."
        ))

    @staticmethod
    def _domain_contract(code):
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
