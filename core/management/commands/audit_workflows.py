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
        required_domain_workflows = {
            "contract_approval",
            "contract_termination",
            "asset_valuation_approval",
            "asset_policy_approval",
            "asset_endorsement_approval",
            "person_change",
        }
        active_domain_codes = set(
            WorkflowDefinition.objects.filter(
                code__in=required_domain_workflows,
                is_active=True,
            ).values_list("code", flat=True)
        )
        for missing_code in sorted(required_domain_workflows - active_domain_codes):
            errors.append(f"Missing active domain workflow: {missing_code}")

        for definition in WorkflowDefinition.objects.filter(
            code__in=required_domain_workflows,
            is_active=True,
        ).prefetch_related("steps", "transitions"):
            initial_steps = [step for step in definition.steps.all() if step.is_initial]
            if len(initial_steps) != 1:
                errors.append(
                    f"{definition.code}: expected exactly one initial step, found {len(initial_steps)}"
                )
            for step in definition.steps.all():
                if not step.is_terminal and not definition.transitions.filter(source_step=step).exists():
                    errors.append(f"{definition.code}/{step.code}: non-terminal step has no outgoing transition")
                if "*" in (step.allowed_roles or []):
                    errors.append(f"{definition.code}/{step.code}: wildcard role is forbidden")
            for transition in definition.transitions.all():
                if "*" in (transition.allowed_roles or []) or "*" in (transition.recipient_roles or []):
                    errors.append(f"{definition.code}/{transition.action_code}: wildcard role is forbidden")
                if transition.closes_case and "insurer_rep" in (transition.allowed_roles or []):
                    errors.append(f"{definition.code}/{transition.action_code}: insurer representative cannot close a case")

        person_change = WorkflowDefinition.objects.filter(
            code="person_change", is_active=True
        ).order_by("-version").first()
        if person_change:
            transitions = {
                transition.action_code: transition
                for transition in person_change.transitions.all()
            }
            refer = transitions.get("refer_to_insurer")
            returned = transitions.get("return_to_company")
            final = transitions.get("approve_and_close")
            if not refer or "insurer_rep" not in (refer.recipient_roles or []):
                errors.append("person_change: initial company representative must route to insurer representative")
            if not returned or "subsidiary_rep" not in (returned.recipient_roles or []):
                errors.append("person_change: insurer representative must return the request to company representative")
            if not final or not final.closes_case or "subsidiary_rep" not in (final.allowed_roles or []):
                errors.append("person_change: only company representative can perform final approval and closure")
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
                    initial_roles = set(initial.allowed_roles or [])
                    allowed_initial_roles = {
                        RoleAssignment.Role.SUBSIDIARY_REP,
                        RoleAssignment.Role.DEPARTMENT_HEAD,
                        RoleAssignment.Role.SYSTEM_ADMIN,
                    }
                    if (
                        RoleAssignment.Role.SUBSIDIARY_REP not in initial_roles
                        or not initial_roles.issubset(allowed_initial_roles)
                    ):
                        errors.append("person_change: مرحله آغازین باید به نماینده شرکت/مدیر مجاز واگذار شود.")
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
                required_person_edges = (
                    (
                        PersonChangeRequest.Status.COMPANY_REVIEW,
                        PersonChangeRequest.Status.INSURER_UPDATE,
                    ),
                    (
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                    ),
                    (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.APPROVED,
                    ),
                    (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.REJECTED,
                    ),
                )
                for source_code, target_code in required_person_edges:
                    if not any(
                        transition.source_step.code == source_code
                        and transition.target_step
                        and transition.target_step.code == target_code
                        for transition in transitions
                    ):
                        errors.append(
                            f"person_change: مسیر {source_code} به {target_code} تعریف نشده است."
                        )
                required_step_roles = {
                    PersonChangeRequest.Status.INSURER_UPDATE: RoleAssignment.Role.INSURER_REP,
                    PersonChangeRequest.Status.COMPANY_FINAL_REVIEW: RoleAssignment.Role.SUBSIDIARY_REP,
                    PersonChangeRequest.Status.APPROVED: RoleAssignment.Role.SUBSIDIARY_REP,
                    PersonChangeRequest.Status.REJECTED: RoleAssignment.Role.SUBSIDIARY_REP,
                }
                for step_code, required_role in required_step_roles.items():
                    step = next((item for item in steps if item.code == step_code), None)
                    if step and required_role not in (step.allowed_roles or []):
                        errors.append(
                            f"person_change/{step_code}: نقش {required_role} باید مجاز باشد."
                        )
                required_person_edges = {
                    (
                        PersonChangeRequest.Status.COMPANY_REVIEW,
                        PersonChangeRequest.Status.INSURER_UPDATE,
                    ),
                    (
                        PersonChangeRequest.Status.INSURER_UPDATE,
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                    ),
                    (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.APPROVED,
                    ),
                    (
                        PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        PersonChangeRequest.Status.REJECTED,
                    ),
                }
                for source_code, target_code in required_person_edges:
                    if not any(
                        transition.source_step.code == source_code
                        and transition.target_step
                        and transition.target_step.code == target_code
                        for transition in transitions
                    ):
                        errors.append(
                            f"person_change: مسیر {source_code} به {target_code} تعریف نشده است."
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

                if code == "person_change":
                    source_code = transition.source_step.code
                    target_code = transition.target_step.code if transition.target_step else None
                    allowed_roles = set(
                        transition.allowed_roles or transition.source_step.allowed_roles
                    )
                    recipient_roles = set(
                        transition.recipient_roles
                        or (transition.target_step.allowed_roles if transition.target_step else [])
                    )
                    company_approvers = {
                        RoleAssignment.Role.SUBSIDIARY_REP,
                        RoleAssignment.Role.DEPARTMENT_HEAD,
                        RoleAssignment.Role.SYSTEM_ADMIN,
                    }
                    if (
                        source_code == PersonChangeRequest.Status.COMPANY_REVIEW
                        and target_code == PersonChangeRequest.Status.INSURER_UPDATE
                    ):
                        if (
                            not allowed_roles.issubset(company_approvers)
                            or RoleAssignment.Role.SUBSIDIARY_REP not in allowed_roles
                        ):
                            errors.append("person_change: ارجاع به بیمه‌گر فقط از نماینده شرکت/مدیر مجاز است.")
                        if RoleAssignment.Role.INSURER_REP not in recipient_roles:
                            errors.append("person_change: مرحله اقدام بیمه‌گر باید به نماینده/کارشناس بیمه‌گر ارجاع شود.")
                        if not recipient_roles.issubset({
                            RoleAssignment.Role.INSURER_REP,
                            RoleAssignment.Role.SYSTEM_ADMIN,
                            RoleAssignment.Role.DEPARTMENT_HEAD,
                        }):
                            errors.append("person_change: ارجاع مرحله بیمه‌گر نباید به نقش شرکت یا متقاضی باشد.")
                    if (
                        source_code == PersonChangeRequest.Status.INSURER_UPDATE
                        and target_code == PersonChangeRequest.Status.COMPANY_FINAL_REVIEW
                    ):
                        if RoleAssignment.Role.INSURER_REP not in allowed_roles:
                            errors.append("person_change: بازگشت از بیمه‌گر باید توسط نقش بیمه‌گر انجام شود.")
                        if RoleAssignment.Role.SUBSIDIARY_REP not in recipient_roles:
                            errors.append("person_change: بازبینی نهایی باید به نماینده شرکت بازگردد.")
                        if not recipient_roles.issubset({
                            RoleAssignment.Role.SUBSIDIARY_REP,
                            RoleAssignment.Role.DEPARTMENT_HEAD,
                            RoleAssignment.Role.SYSTEM_ADMIN,
                        }):
                            errors.append("person_change: مرحله بازبینی نهایی نباید به نقش بیمه‌گر ارجاع شود.")
                    if (
                        source_code == PersonChangeRequest.Status.COMPANY_FINAL_REVIEW
                        and target_code in {
                            PersonChangeRequest.Status.APPROVED,
                            PersonChangeRequest.Status.REJECTED,
                        }
                    ):
                        if (
                            not allowed_roles.issubset(company_approvers)
                            or RoleAssignment.Role.SUBSIDIARY_REP not in allowed_roles
                            or RoleAssignment.Role.SUBSIDIARY_REP not in recipient_roles
                        ):
                            errors.append("person_change: تصمیم نهایی درخواست متقاضی فقط برای نماینده شرکت/مدیر مجاز است.")
                    if transition.closes_case:
                        if source_code not in {
                            PersonChangeRequest.Status.APPROVED,
                            PersonChangeRequest.Status.REJECTED,
                            PersonChangeRequest.Status.COMPANY_FINAL_REVIEW,
                        }:
                            errors.append("person_change: بستن درخواست فقط پس از بازبینی نهایی شرکت مجاز است.")
                        if not allowed_roles.issubset(company_approvers):
                            errors.append("person_change: بستن درخواست فقط برای نماینده شرکت/رئیس/مدیر سامانه مجاز است.")

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
