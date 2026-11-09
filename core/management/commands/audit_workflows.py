from django.core.management.base import BaseCommand, CommandError

from accounts.models import RoleAssignment
from claims.models import ClaimObjection
from insurance.models import ContractRevision
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowDefinition


class Command(BaseCommand):
    help = "ممیزی پوشش و سازگاری گردش‌کارهای فعال پیش از انتشار."

    def handle(self, *args, **options):
        required_codes = {value for value, _label in ServiceRequest.Kind.choices} | {"claim_objection", "contract_approval", "contract_termination"}
        definitions = {
            item.code: item
            for item in WorkflowDefinition.objects.filter(
                code__in=required_codes,
                is_active=True,
            ).prefetch_related("steps__outgoing_transitions")
        }
        missing = sorted(required_codes - set(definitions))
        errors = []

        for code, definition in sorted(definitions.items()):
            steps = list(definition.steps.all())
            initial_steps = [step for step in steps if step.is_initial]
            valid_statuses = set(dict(
                ClaimObjection.Status.choices if code == "claim_objection"
                else ContractRevision.Status.choices if code in {"contract_approval", "contract_termination"}
                else ServiceRequest.Status.choices
            ))
            for step in steps:
                if step.code not in valid_statuses:
                    errors.append(
                        f"{code}/{step.code}: کد مرحله باید با یکی از وضعیت‌های مدل دامنه یکسان باشد تا وضعیت همگام بماند."
                    )
            if code == "contract_approval":
                decision_steps = {ContractRevision.Status.APPROVED, ContractRevision.Status.REJECTED}
            elif code == "contract_termination":
                decision_steps = {ContractRevision.Status.TERMINATED, ContractRevision.Status.REJECTED}
            else:
                decision_steps = set()
            for decision_code in sorted(decision_steps):
                decision_step = next((step for step in steps if step.code == decision_code), None)
                if decision_step is None:
                    errors.append(f"{code}: مرحله تصمیم نهایی {decision_code} تعریف نشده است.")
                elif not any(item.closes_case for item in decision_step.outgoing_transitions.all()):
                    errors.append(f"{code}/{decision_code}: تصمیم نهایی باید مسیر بستن پرونده داشته باشد.")
            if len(initial_steps) != 1:
                errors.append(f"{code}: باید دقیقاً یک مرحله آغازین داشته باشد.")
            step_ids = {step.pk for step in steps}
            for step in steps:
                if not step.allowed_roles:
                    errors.append(f"{code}/{step.code}: نقش مجاز مرحله خالی است.")
                if "*" in (step.allowed_roles or []):
                    errors.append(f"{code}/{step.code}: نقش عمومی * مجاز نیست.")
                if not step.is_terminal and not step.outgoing_transitions.exists():
                    errors.append(f"{code}/{step.code}: مرحله غیرپایانی مسیر خروجی ندارد.")
            for transition in definition.transitions.select_related("source_step", "target_step"):
                if transition.source_step_id not in step_ids:
                    errors.append(f"{code}/{transition.action_code}: مرحله مبدأ خارج از تعریف است.")
                if transition.target_step_id and transition.target_step_id not in step_ids:
                    errors.append(f"{code}/{transition.action_code}: مرحله مقصد خارج از تعریف است.")
                if transition.closes_case and RoleAssignment.Role.INSURER_REP in (transition.allowed_roles or []):
                    errors.append(f"{code}/{transition.action_code}: نماینده بیمه‌گر نباید پرونده را نهایی ببندد.")
                if code in {"contract_approval", "contract_termination"} and transition.closes_case:
                    expected_final_steps = (
                        {ContractRevision.Status.APPROVED, ContractRevision.Status.REJECTED}
                        if code == "contract_approval"
                        else {ContractRevision.Status.TERMINATED, ContractRevision.Status.REJECTED}
                    )
                    if transition.source_step.code not in expected_final_steps:
                        errors.append(
                            f"{code}/{transition.action_code}: بستن پرونده باید از مرحله تصمیم نهایی انجام شود."
                        )
                if code in {"claim_objection", "contract_approval", "contract_termination"} and transition.closes_case:
                    closing_roles = set(transition.allowed_roles or transition.source_step.allowed_roles)
                    authorized_closers = {
                        RoleAssignment.Role.DEPARTMENT_HEAD,
                        RoleAssignment.Role.SYSTEM_ADMIN,
                    }
                    if not closing_roles or not closing_roles.issubset(authorized_closers):
                        errors.append(
                            f"{code}/{transition.action_code}: بستن/تأیید نهایی فقط برای رئیس اداره یا مدیر سامانه مجاز است."
                        )
                if not transition.closes_case and not (
                    transition.recipient_roles or (transition.target_step and transition.target_step.allowed_roles)
                ):
                    errors.append(f"{code}/{transition.action_code}: نقش گیرنده مسیر مشخص نیست.")
                if "*" in (transition.allowed_roles or []) or "*" in (transition.recipient_roles or []):
                    errors.append(f"{code}/{transition.action_code}: نقش عمومی * مجاز نیست.")

        if missing:
            self.stdout.write(self.style.ERROR(
                "گردش‌کار فعال برای این نوع درخواست‌ها تعریف نشده است: " + ", ".join(missing)
            ))
        for error in errors:
            self.stdout.write(self.style.ERROR(error))
        if missing or errors:
            raise CommandError(
                f"ممیزی گردش‌کار ناموفق بود؛ {len(missing)} نوع درخواست بدون گردش‌کار و {len(errors)} مغایرت."
            )
        self.stdout.write(self.style.SUCCESS(
            f"ممیزی موفق: {len(required_codes)} نوع درخواست دارای گردش‌کار فعال و معتبر است."
        ))
