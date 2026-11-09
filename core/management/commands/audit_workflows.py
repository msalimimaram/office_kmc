from django.core.management.base import BaseCommand, CommandError

from accounts.models import RoleAssignment
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowDefinition


class Command(BaseCommand):
    help = "ممیزی پوشش و سازگاری گردش‌کارهای فعال پیش از انتشار."

    def handle(self, *args, **options):
        required_codes = {value for value, _label in ServiceRequest.Kind.choices}
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
