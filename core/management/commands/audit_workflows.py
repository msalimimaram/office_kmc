from django.core.management.base import BaseCommand, CommandError

from accounts.models import RoleAssignment
from claims.models import ClaimObjection
from insurance.models import ContractRevision
from requests_portal.models import ServiceRequest
from organizations.models import PersonChangeRequest
from workflow.models import WorkflowDefinition


class Command(BaseCommand):
    help = "ممیزی پوشش و سازگاری گردش‌کارهای فعال پیش از انتشار."

    def handle(self, *args, **options):
        required_codes = (
            {value for value, _label in ServiceRequest.Kind.choices}
            | {"claim_objection", "contract_approval", "contract_termination", "person_change"}
        )
        active_definitions = list(
            WorkflowDefinition.objects.filter(
                code__in=required_codes,
                is_active=True,
            ).prefetch_related("steps__outgoing_transitions")
        )
        errors = []
        definitions = {}
        for definition in active_definitions:
            if definition.code in definitions:
                errors.append(
                    f"{definition.code}: بیش از یک نسخه فعال گردش‌کار وجود دارد."
                )
            definitions[definition.code] = definition

        missing = sorted(required_codes - set(definitions))
        authorized_approvers = {
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.SYSTEM_ADMIN,
        }

        for code, definition in sorted(definitions.items()):
            steps = list(definition.steps.all())
            transitions = list(
                definition.transitions.select_related("source_step", "target_step")
            )
            initial_steps = [step for step in steps if step.is_initial]
            if len(initial_steps) != 1:
                errors.append(f"{code}: باید دقیقاً یک مرحله آغازین داشته باشد.")

            if code == "claim_objection":
                valid_statuses = set(dict(ClaimObjection.Status.choices))
                decision_steps = set()
            elif code in {"contract_approval", "contract_termination"}:
                valid_statuses = set(dict(ContractRevision.Status.choices))
                decision_steps = (
                    {ContractRevision.Status.APPROVED, ContractRevision.Status.REJECTED}
                    if code == "contract_approval"
                    else {ContractRevision.Status.TERMINATED, ContractRevision.Status.REJECTED}
                )
                if len(initial_steps) == 1:
                    initial = initial_steps[0]
                    if initial.code != ContractRevision.Status.PENDING_APPROVAL:
                        errors.append(
                            f"{code}: مرحله آغازین باید pending_approval باشد."
                        )
                    if not initial.allowed_roles or not set(initial.allowed_roles).issubset(
                        authorized_approvers
                    ):
                        errors.append(
                            f"{code}: مرحله آغازین فقط باید به رئیس اداره/مدیر سامانه واگذار شود."
                        )
            elif code == "person_change":
                valid_statuses = set(dict(PersonChangeRequest.Status.choices))
                decision_steps = {
                    PersonChangeRequest.Status.APPROVED,
                    PersonChangeRequest.Status.REJECTED,
                }
                if len(initial_steps) == 1:
                    initial = initial_steps[0]
                    if initial.code != PersonChangeRequest.Status.COMPANY_REVIEW:
                        errors.append("person_change: مرحله آغازین باید company_review باشد.")
                    if RoleAssignment.Role.SUBSIDIARY_REP not in (initial.allowed_roles or []):
                        errors.append("person_change: مرحله آغازین باید به نماینده شرکت واگذار شود.")
                required_person_steps = {
                    PersonChangeRequest.Status.INSURER_UPDATE,
                    PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                }
                missing_person_steps = required_person_steps - {step.code for step in steps}
                if missing_person_steps:
                    errors.append(
                        "person_change: مراحل ضروری تعریف نشده‌اند: "
                        + ", ".join(sorted(missing_person_steps))
                    )
            else:
                valid_statuses = set(dict(ServiceRequest.Status.choices))
                decision_steps = set()

            for step in steps:
                if step.code not in valid_statuses:
                    errors.append(
                        f"{code}/{step.code}: کد مرحله باید با یکی از وضعیت‌های مدل دامنه یکسان باشد."
                    )
                if not step.allowed_roles:
                    errors.append(f"{code}/{step.code}: نقش مجاز مرحله خالی است.")
                if "*" in (step.allowed_roles or []):
                    errors.append(f"{code}/{step.code}: نقش عمومی * مجاز نیست.")
                if not step.is_terminal and not step.outgoing_transitions.exists():
                    errors.append(f"{code}/{step.code}: مرحله غیرپایانی مسیر خروجی ندارد.")

            for decision_code in sorted(decision_steps):
                decision_step = next(
                    (step for step in steps if step.code == decision_code), None
                )
                if decision_step is None:
                    errors.append(f"{code}: مرحله تصمیم نهایی {decision_code} تعریف نشده است.")
                    continue
                if not any(item.closes_case for item in decision_step.outgoing_transitions.all()):
                    errors.append(
                        f"{code}/{decision_code}: تصمیم نهایی باید مسیر بستن پرونده داشته باشد."
                    )
                if not any(item.target_step_id == decision_step.pk for item in transitions):
                    errors.append(
                        f"{code}/{decision_code}: مرحله تصمیم نهایی از مسیر گردش‌کار قابل دسترسی نیست."
                    )

            for transition in transitions:
                if transition.source_step_id not in {step.pk for step in steps}:
                    errors.append(f"{code}/{transition.action_code}: مرحله مبدأ خارج از تعریف است.")
                if transition.target_step_id and transition.target_step_id not in {
                    step.pk for step in steps
                }:
                    errors.append(f"{code}/{transition.action_code}: مرحله مقصد خارج از تعریف است.")

                if transition.closes_case and RoleAssignment.Role.INSURER_REP in (
                    transition.allowed_roles or []
                ):
                    errors.append(
                        f"{code}/{transition.action_code}: نماینده بیمه‌گر نباید پرونده را نهایی ببندد."
                    )

                if code in {"contract_approval", "contract_termination"}:
                    expected_final_steps = (
                        {ContractRevision.Status.APPROVED, ContractRevision.Status.REJECTED}
                        if code == "contract_approval"
                        else {ContractRevision.Status.TERMINATED, ContractRevision.Status.REJECTED}
                    )
                    if transition.closes_case and transition.source_step.code not in expected_final_steps:
                        errors.append(
                            f"{code}/{transition.action_code}: بستن پرونده باید از مرحله تصمیم نهایی انجام شود."
                        )
                    if (
                        not transition.closes_case
                        and transition.target_step
                        and transition.target_step.code in expected_final_steps
                    ):
                        recipients = set(
                            transition.recipient_roles or transition.target_step.allowed_roles
                        )
                        if not recipients or not recipients.issubset(authorized_approvers):
                            errors.append(
                                f"{code}/{transition.action_code}: مرحله تصمیم فقط باید به رئیس اداره/مدیر سامانه ارجاع شود."
                            )

                if code in {"claim_objection", "contract_approval", "contract_termination"} and transition.closes_case:
                    closing_roles = set(
                        transition.allowed_roles or transition.source_step.allowed_roles
                    )
                    if not closing_roles or not closing_roles.issubset(authorized_approvers):
                        errors.append(
                            f"{code}/{transition.action_code}: بستن/تأیید نهایی فقط برای رئیس اداره یا مدیر سامانه مجاز است."
                        )

                if not transition.closes_case and not (
                    transition.recipient_roles
                    or (transition.target_step and transition.target_step.allowed_roles)
                ):
                    errors.append(
                        f"{code}/{transition.action_code}: نقش گیرنده مسیر مشخص نیست."
                    )
                if "*" in (transition.allowed_roles or []) or "*" in (
                    transition.recipient_roles or []
                ):
                    errors.append(f"{code}/{transition.action_code}: نقش عمومی * مجاز نیست.")

        if missing:
            self.stdout.write(self.style.ERROR(
                "گردش‌کار فعال برای این فرآیندها تعریف نشده است: " + ", ".join(missing)
            ))
        for error in errors:
            self.stdout.write(self.style.ERROR(error))
        if missing or errors:
            raise CommandError(
                f"ممیزی گردش‌کار ناموفق بود؛ {len(missing)} فرآیند فاقد گردش‌کار و "
                f"{len(errors)} مغایرت."
            )
        self.stdout.write(self.style.SUCCESS(
            f"ممیزی موفق: هر {len(required_codes)} فرآیند دارای گردش‌کار فعال و معتبر است."
        ))
