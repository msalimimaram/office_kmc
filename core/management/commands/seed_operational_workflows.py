from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Max
from django.utils import timezone

from accounts.models import RoleAssignment
from workflow.models import WorkflowDefinition, WorkflowStep, WorkflowTransition


class Command(BaseCommand):
    help = "Create the approved baseline approval workflows for contracts and insured assets."

    WORKFLOWS = (
        ("contract_approval", "تأیید قرارداد", "approved"),
        ("contract_termination", "تأیید فسخ قرارداد", "terminated"),
        ("asset_valuation_approval", "تأیید ارزیابی دارایی", "approved"),
        ("asset_policy_approval", "تأیید دوره بیمه‌نامه دارایی", "approved"),
        ("asset_endorsement_approval", "تأیید الحاقیه دارایی", "approved"),
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        eligible_roles = [
            RoleAssignment.Role.DEPARTMENT_HEAD,
            RoleAssignment.Role.SYSTEM_ADMIN,
        ]
        assignment = (
            RoleAssignment.objects.filter(
                role__in=eligible_roles,
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
        roles = [RoleAssignment.Role.DEPARTMENT_HEAD, RoleAssignment.Role.SYSTEM_ADMIN]
        created = []
        skipped = []

        for code, title, approved_step_code in self.WORKFLOWS:
            if WorkflowDefinition.objects.filter(code=code, is_active=True).exists():
                skipped.append(code)
                continue

            latest_version = (
                WorkflowDefinition.objects.filter(code=code)
                .aggregate(value=Max("version"))["value"]
                or 0
            )
            definition = WorkflowDefinition.objects.create(
                code=code,
                title=title,
                version=latest_version + 1,
                created_by=actor,
                description=(
                    "گردش پایه نسخه‌دار؛ تأیید و رد فقط توسط رئیس اداره بیمه "
                    "یا مدیر سامانه انجام می‌شود. برای تغییر مسیر، نسخه جدید منتشر کنید."
                ),
            )
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

            definition.approved_by = actor
            definition.is_active = True
            definition.save()
            created.append(code)

        if created:
            self.stdout.write(self.style.SUCCESS("Created and published: " + ", ".join(created)))
        if skipped:
            self.stdout.write("Already active; left unchanged: " + ", ".join(skipped))
        self.stdout.write(
            "Initial approval is assigned to an active Department Head/System Admin. "
            "No insurer representative is authorized to approve or close these workflows."
        )
