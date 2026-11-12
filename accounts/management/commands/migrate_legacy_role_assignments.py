from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import PositionAssignment, RoleAssignment, User
from claims.models import Claim
from insurance.models import Insurer
from organizations.models import Company, Person, PersonEmployment


class Command(BaseCommand):
    help = (
        "انتقال کنترل‌شده نقش‌های قدیمی User.role به RoleAssignment؛ "
        "اجرای پیش‌فرض فقط dry-run است."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="ثبت واقعی انتصاب‌های معتبر؛ بدون این گزینه هیچ تغییری ذخیره نمی‌شود.",
        )
        parser.add_argument(
            "--user-id",
            type=int,
            help="محدودکردن مهاجرت به یک حساب مشخص برای بررسی موردی.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        user_id = options.get("user_id")
        users = User.objects.filter(is_active=True).order_by("pk")
        if user_id is not None:
            users = users.filter(pk=user_id)
            if not users.exists():
                raise CommandError(f"حساب فعال با شناسه {user_id} پیدا نشد.")

        today = timezone.localdate()
        created = 0
        skipped = 0
        failed = 0

        # A single outer transaction allows dry-run to execute the exact model
        # validation and uniqueness checks, then roll every write back.
        with transaction.atomic():
            for user in users.iterator():
                try:
                    with transaction.atomic():
                        reason = self._existing_history_reason(user)
                        if reason:
                            skipped += 1
                            self.stdout.write(
                                self.style.WARNING(f"SKIP {user.pk} ({user.username}): {reason}")
                            )
                            continue

                        attributes, reason = self._legacy_assignment(user, today)
                        if attributes is None:
                            skipped += 1
                            self.stdout.write(
                                self.style.WARNING(f"SKIP {user.pk} ({user.username}): {reason}")
                            )
                            continue

                        assignment = RoleAssignment(user=user, **attributes)
                        assignment.save()
                        created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"READY {user.pk} ({user.username}): "
                                f"{assignment.get_role_display()}"
                            )
                        )
                except (ValidationError, IntegrityError) as exc:
                    failed += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"FAILED {user.pk} ({user.username}): {exc}"
                        )
                    )

            if not apply_changes:
                transaction.set_rollback(True)

        mode = "APPLIED" if apply_changes else "DRY RUN — no database changes saved"
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(mode))
        self.stdout.write(
            f"قابل ایجاد/ایجادشده: {created} | ردشده یا نیازمند بررسی: {skipped} | خطا: {failed}"
        )
        if not apply_changes:
            self.stdout.write(
                "برای ثبت واقعی، پس از بازبینی گزارش همین فرمان را با --apply اجرا کنید."
            )

    @staticmethod
    def _existing_history_reason(user):
        if RoleAssignment.objects.filter(user_id=user.pk).exists():
            return "برای این حساب سابقه انتصاب وجود دارد؛ از بازنویسی خودکار جلوگیری شد."
        if PositionAssignment.objects.filter(user_id=user.pk).exists():
            return "برای این حساب سابقه سمت سازمانی وجود دارد؛ مهاجرت خودکار متوقف شد."
        return None

    @staticmethod
    def _legacy_assignment(user, today):
        role = user.role
        reason = (
            f"مهاجرت کنترل‌شده از User.role قدیمی در تاریخ {today.isoformat()}؛ "
            "محدوده از داده‌های معتبر همان حساب استخراج شده است."
        )
        base = {
            "valid_from": today,
            "is_active": True,
            "reason": reason,
        }

        if role == "system_admin":
            return {**base, "role": RoleAssignment.Role.SYSTEM_ADMIN}, None

        if role == "department_head":
            return {**base, "role": RoleAssignment.Role.DEPARTMENT_HEAD}, None

        if role == "insurer":
            if not user.insurer_id or not Insurer.objects.filter(
                pk=user.insurer_id,
                is_active=True,
            ).exists():
                return None, "بیمه‌گر فعال و قابل اثبات برای این حساب وجود ندارد."
            return {
                **base,
                "role": RoleAssignment.Role.INSURER_REP,
                "insurer_id": user.insurer_id,
            }, None

        if role == "subsidiary_rep":
            if not user.company_id or not Company.objects.filter(
                pk=user.company_id,
                is_active=True,
            ).exists():
                return None, "شرکت فعال و مشخص برای نماینده وجود ندارد."

            person = Person.objects.filter(user_id=user.pk).select_related(
                "employee"
            ).first()
            if not person:
                return None, "هویت Person متصل به حساب پیدا نشد."
            if (
                person.relationship != Person.Relationship.EMPLOYEE
                and not person.employee_id
            ):
                return None, "فرد تحت تکفل به بیمه‌شده اصلی متصل نیست."

            primary_person = person.employee if person.employee_id else person
            employment = PersonEmployment.objects.filter(
                person_id=primary_person.pk,
                company_id=user.company_id,
                status=PersonEmployment.Status.ACTIVE,
            ).filter(
                Q(valid_from__isnull=True) | Q(valid_from__lte=today)
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=today)
            ).order_by("-valid_from", "-pk").first()

            if not employment:
                return None, "اشتغال فعال و تاریخ‌دار در همان شرکت قابل اثبات نیست."

            return {
                **base,
                "role": RoleAssignment.Role.SUBSIDIARY_REP,
                "company_id": user.company_id,
                "line_code": "*",
                "valid_until": employment.valid_until,
            }, None

        if role == "employee":
            person = Person.objects.filter(user_id=user.pk).first()
            if not person or person.relationship != Person.Relationship.EMPLOYEE:
                return None, "شخص اصلی با اتصال مستقیم به حساب پیدا نشد."

            has_claim_history = Claim.objects.filter(
                Q(person_id=person.pk) | Q(primary_insured_id=person.pk)
            ).exists()
            if not ((person.is_active and person.is_insured) or has_claim_history):
                return None, "پوشش جاری یا سابقه خسارت برای احراز سابقه بیمه‌شدگی وجود ندارد."

            return {
                **base,
                "role": RoleAssignment.Role.INSURED_PERSON,
            }, None

        if role == "insurance_specialist":
            return None, (
                "کارشناس فاقد رشته بیمه‌ای مشخص است؛ انتصاب line_code باید دستی تعیین شود "
                "و مجوز کلی حدس زده نمی‌شود."
            )

        if role in {"finance", "legal", "auditor"}:
            return None, (
                "این نقش قدیمی از مدل کسب‌وکار حذف شده است؛ تبدیل خودکار یا اعطای نقش جایگزین مجاز نیست."
            )

        return None, f"نقش قدیمی پشتیبانی‌نشده است: {role!r}"
