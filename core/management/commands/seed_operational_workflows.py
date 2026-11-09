from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, Max
from django.utils import timezone

from accounts.models import RoleAssignment
from workflow.models import WorkflowDefinition, WorkflowStep, WorkflowTransition


class Command(BaseCommand):
    help = "Publish baseline approval workflows for contracts, assets, and insured-person changes."

    WORKFLOWS = (
        ("contract_approval", "تأیید قرارداد", "approved"),
        ("contract_termination", "تأیید فسخ قرارداد", "terminated"),
        ("asset_valuation_approval", "تأیید ارزیابی دارایی", "approved"),
        ("asset_policy_approval", "تأیید دوره بیمه‌نامه دارایی", "approved"),
        ("asset_endorsement_approval", "تأیید الحاقیه دارایی", "approved"),
        ("person_change", "اصلاح اطلاعات بیمه‌شده", "approved"),
    )

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
            if WorkflowDefinition.objects.filter(code=code, is_active=True).exists():
                skipped.append(code)
                continue
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
                    "گردش پایه نسخه‌دار. تغییر مسیر فقط با ایجاد و انتشار نسخه جدید "
                    "و تأیید رئیس اداره بیمه یا مدیر سامانه مجاز است."
                ),
            )
            if code == "person_change":
                self._build_person_change(definition)
            else:
                self._build_global_approval(definition, approved_step_code, global_roles)
            definition.approved_by = actor
            definition.is_active = True
            definition.save()
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
        insurer_roles = [RoleAssignment.Role.INSURER]
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
