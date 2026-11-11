from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import RoleAssignment, User
from claims.models import Claim, ClaimPayment
from insurance.models import Contract, Insurer, InsuranceLine
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest


SEED_DATE = date(2026, 11, 10)


def _get_or_create_unchanged(model, *, lookup, defaults, verify_fields=None):
    """
    Create a namespaced fixture row, or reuse it without ever updating it.

    A conflicting pre-existing row aborts the enclosing transaction instead
    of silently rewriting potentially meaningful local data.
    """
    obj = model.objects.filter(**lookup).first()
    if obj is not None:
        # Fixture values may be specified either as lookup keys or as defaults.
        # This matters for immutable/source identifiers such as source_reference,
        # and for scoped relations included in the natural-key lookup.
        expected_values = dict(lookup)
        expected_values.update(defaults)
        fields = tuple(verify_fields) if verify_fields is not None else tuple(expected_values)
        missing_fields = [field for field in fields if field not in expected_values]
        if missing_fields:
            raise CommandError(
                f"Invalid seed verification for {model._meta.label} ({lookup}): "
                f"no expected value supplied for: {', '.join(missing_fields)}."
            )
        mismatches = [
            field for field in fields
            if getattr(obj, field) != expected_values[field]
        ]
        if mismatches:
            label = ", ".join(mismatches)
            raise CommandError(
                f"Seed collision in {model._meta.label} ({lookup}): "
                f"existing values differ for: {label}. No existing data was changed."
            )
        return obj, False

    return model.objects.create(**lookup, **defaults), True


class Command(BaseCommand):
    help = "ایجاد داده نمونه غیرمخرب برای تست محلی؛ فقط در DEBUG مجاز است."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo فقط در محیط DEBUG قابل اجراست.")

        created_counts = {}
        reused_counts = {}

        def record(model, lookup, defaults, verify_fields=None):
            obj, created = _get_or_create_unchanged(
                model,
                lookup=lookup,
                defaults=defaults,
                verify_fields=verify_fields,
            )
            bucket = created_counts if created else reused_counts
            bucket[model._meta.label] = bucket.get(model._meta.label, 0) + 1
            return obj, created

        company_a, company_a_created = record(
            Company,
            {"code": "DEMO-A"},
            {"name": "شرکت نمونه الف", "is_parent": True, "is_active": True},
        )
        company_b, company_b_created = record(
            Company,
            {"code": "DEMO-B"},
            {"name": "شرکت نمونه ب", "is_parent": False, "is_active": True},
        )
        insurer, _ = record(
            Insurer,
            {"name": "بیمه‌گر نمونه"},
            {"is_active": True},
        )

        contract, contract_created = record(
            Contract,
            {"code": "DEMO-1405"},
            {
                "title": "قرارداد نمونه درمان تکمیلی",
                "insurer": insurer,
                "line": InsuranceLine.HEALTH,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 29),
                "status": Contract.Status.ACTIVE,
                "is_active": True,
            },
            verify_fields=("title", "insurer", "line", "start_date", "end_date"),
        )
        expected_company_ids = {company_a.pk, company_b.pk}
        if contract_created:
            contract.companies.set([company_a, company_b])
        elif set(contract.companies.values_list("pk", flat=True)) != expected_company_ids:
            raise CommandError(
                "Seed collision in Contract.companies: existing company scope differs. "
                "No existing data was changed."
            )

        employee_a, _ = record(
            Person,
            {"national_id": "0012345678"},
            {
                "company": company_a,
                "personnel_code": "A-1001",
                "first_name": "علی",
                "last_name": "نمونه",
                "birth_date": date(1988, 5, 12),
                "relationship": Person.Relationship.EMPLOYEE,
                "is_insured": True,
                "is_active": True,
            },
            verify_fields=("company", "personnel_code", "first_name", "last_name", "birth_date", "relationship"),
        )
        record(
            Person,
            {"national_id": "0012345679"},
            {
                "company": company_a,
                "personnel_code": "A-1001-01",
                "first_name": "سارا",
                "last_name": "نمونه",
                "birth_date": date(1990, 8, 4),
                "relationship": Person.Relationship.SPOUSE,
                "employee": employee_a,
                "is_insured": True,
                "is_active": True,
            },
            verify_fields=("company", "personnel_code", "first_name", "last_name", "birth_date", "relationship"),
        )
        employee_b, _ = record(
            Person,
            {"national_id": "0098765432"},
            {
                "company": company_b,
                "personnel_code": "B-2001",
                "first_name": "رضا",
                "last_name": "آزمایشی",
                "birth_date": date(1985, 3, 22),
                "relationship": Person.Relationship.EMPLOYEE,
                "is_insured": True,
                "is_active": True,
            },
            verify_fields=("company", "personnel_code", "first_name", "last_name", "birth_date", "relationship"),
        )

        import os
        demo_password = os.environ.get("PRESENTATION_DEMO_PASSWORD", "")
        if not demo_password:
            raise CommandError("Set PRESENTATION_DEMO_PASSWORD in the environment before creating demo accounts.")
        user_specs = (
            ("Admin", User.Role.SYSTEM_ADMIN, None, "", None, "مدیر", "سامانه", "", ("",)),
            ("Shahamat", User.Role.DEPARTMENT_HEAD, None, "", None, "رئیس", "اداره بیمه", "", ("",)),
            ("Salimi", User.Role.INSURANCE_SPECIALIST, None, "", None, "سرپرست", "بیمه تکمیلی درمان", "09120000001", ("health",)),
            ("Amiri", User.Role.INSURANCE_SPECIALIST, None, "", None, "کارشناس", "بیمه تکمیلی درمان", "09120000002", ("health",)),
            ("Delbari", User.Role.INSURANCE_SPECIALIST, None, "", None, "مسئول", "بیمه مسئولیت و آتش‌سوزی", "09120000003", ("liability", "fire")),
            ("Mahbod", User.Role.INSURANCE_SPECIALIST, None, "", None, "مسئول", "بیمه‌های خودرو", "09120000004", ("third_party", "body")),
            ("Namayande1", User.Role.SUBSIDIARY_REP, company_a, "", None, "نماینده", "شرکت نمونه الف", "09121110001", ("*",)),
            ("Namayande2", User.Role.SUBSIDIARY_REP, company_b, "", None, "نماینده", "شرکت نمونه ب", "09121110002", ("*",)),
            ("employee.a", User.Role.EMPLOYEE, company_a, employee_a.national_id, None, "علی", "نمونه", "09121111111", ("*",)),
            ("employee.b", User.Role.EMPLOYEE, company_b, employee_b.national_id, None, "رضا", "آزمایشی", "09122222222", ("*",)),
            ("Saman", User.Role.INSURER, None, "", insurer, "نماینده", "بیمه‌گر سامان", "09123330001", ("",)),
        )
        users = {}
        generated_users = []
        for username, role, company, national_id, insurer_obj, first_name, last_name, mobile, line_codes in user_specs:
            defaults = {
                "role": role, "company": company, "national_id": national_id,
                "insurer": insurer_obj, "first_name": first_name, "last_name": last_name,
                "mobile": mobile, "is_active": True, "is_staff": username == "Admin",
                "must_change_password": False,
            }
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(username=username, **defaults)
                user.set_password(demo_password)
                user.save()
                created_counts[User._meta.label] = created_counts.get(User._meta.label, 0) + 1
                generated_users.append(username)
            else:
                for field in ("role", "company", "national_id", "insurer", "is_active"):
                    if getattr(user, field) != defaults[field]:
                        raise CommandError(
                            f"Seed collision in accounts.User (username={username}): "
                            f"{field} differs. Existing account and password were not changed."
                        )
                if not user.has_usable_password():
                    user.set_password(demo_password)
                    user.must_change_password = False
                    user.save(update_fields=["password", "must_change_password"])
                reused_counts[User._meta.label] = reused_counts.get(User._meta.label, 0) + 1
            users[username] = user

        users.update({
            "admin.demo": users["Admin"], "head.demo": users["Shahamat"],
            "supervisor.demo": users["Salimi"], "specialist.demo": users["Amiri"],
            "specialist.fire.demo": users["Delbari"], "companya.demo": users["Namayande1"],
            "companyb.demo": users["Namayande2"], "employee.a": users["employee.a"],
            "employee.b": users["employee.b"], "insurer.demo": users["Saman"],
        })

        assignment_roles = {
            User.Role.SYSTEM_ADMIN: RoleAssignment.Role.SYSTEM_ADMIN,
            User.Role.DEPARTMENT_HEAD: RoleAssignment.Role.DEPARTMENT_HEAD,
            User.Role.INSURANCE_SPECIALIST: RoleAssignment.Role.INSURANCE_SPECIALIST,
            User.Role.SUBSIDIARY_REP: RoleAssignment.Role.SUBSIDIARY_REP,
            User.Role.EMPLOYEE: RoleAssignment.Role.INSURED_PERSON,
            User.Role.INSURER: RoleAssignment.Role.INSURER_REP,
        }
        for username, role, company, _national_id, insurer_obj, _first, _last, _mobile, line_codes in user_specs:
            user = users[username]
            assignment_company = company if role in {User.Role.SUBSIDIARY_REP, User.Role.EMPLOYEE} else None
            assignment_insurer = insurer_obj if role == User.Role.INSURER else None
            for line_code in line_codes:
                record(
                    RoleAssignment,
                    {"user": user, "role": assignment_roles[role], "company": assignment_company,
                     "insurer": assignment_insurer, "line_code": line_code},
                    {"valid_from": date(2026, 1, 1), "valid_until": None, "is_active": True,
                     "reason": "انتصاب کاربر نمایشی مطابق نقش و حوزه خدمت",
                     "granted_by": users["Admin"], "approved_by": users["Shahamat"]},
                    verify_fields=("reason", "granted_by", "approved_by"),
                )

        claim_a, _ = record(
            Claim,
            {"claim_number": "DEMO-CLM-001"},
            {
                "person": employee_a,
                "contract": contract,
                "insurer": insurer,
                "service_date": SEED_DATE,
                "registered_date": SEED_DATE,
                "service_type": "نمونه خدمات درمانی",
                "requested_amount": Decimal("10000000"),
                "assessed_amount": Decimal("8000000"),
                "payable_amount": Decimal("8000000"),
                "paid_amount": Decimal("0"),
                "status": Claim.Status.APPROVED,
                "source_reference": "DEMO",
                "assessment_note": "داده آزمایشی",
            },
            verify_fields=("person", "contract", "insurer", "service_type", "requested_amount", "assessed_amount", "payable_amount", "assessment_note"),
        )
        claim_b, _ = record(
            Claim,
            {"claim_number": "DEMO-CLM-002"},
            {
                "person": employee_b,
                "contract": contract,
                "insurer": insurer,
                "service_date": SEED_DATE,
                "registered_date": SEED_DATE,
                "service_type": "نمونه خسارت شرکت ب",
                "requested_amount": Decimal("5000000"),
                "assessed_amount": Decimal("5000000"),
                "payable_amount": Decimal("5000000"),
                "paid_amount": Decimal("5000000"),
                "payment_date": SEED_DATE,
                "status": Claim.Status.PAID,
                "source_reference": "DEMO",
            },
            verify_fields=("person", "contract", "insurer", "service_type", "requested_amount", "assessed_amount", "payable_amount", "source_reference"),
        )

        record(
            ClaimPayment,
            {"claim": claim_b, "is_legacy_import": True},
            {
                "entry_type": ClaimPayment.EntryType.PAYMENT,
                "amount": Decimal("5000000"),
                "paid_at": SEED_DATE,
                "source_reference": "DEMO-VOUCHER-002",
                "source_insurer": insurer,
                "recorded_by": users["insurer.demo"],
                "confirmed_by": users["head.demo"],
                "note": "پرداخت نمونه منتقل‌شده از منبع؛ صرفاً سابقه اطلاعاتی و بدون انتقال وجه.",
            },
        )

        record(
            ServiceRequest,
            {"reference": "IB-DEMO-001"},
            {
                "kind": ServiceRequest.Kind.DOCUMENT_REQUEST,
                "submitted_by": users["employee.a"],
                "person": employee_a,
                "company": company_a,
                "title": "درخواست نمونه مدارک",
                "description": "درخواست آزمایشی برای تست گردش کار",
                "status": ServiceRequest.Status.SUBMITTED,
                "assigned_to": None,
                "is_confidential": False,
            },
            verify_fields=("kind", "submitted_by", "person", "company", "title", "description", "is_confidential"),
        )
        record(
            ServiceRequest,
            {"reference": "IB-DEMO-002"},
            {
                "kind": ServiceRequest.Kind.MEDICAL_ASSISTANCE,
                "submitted_by": users["employee.a"],
                "person": employee_a,
                "company": company_a,
                "title": "درخواست محرمانه نمونه",
                "description": "درخواست محرمانه آزمایشی",
                "status": ServiceRequest.Status.SUBMITTED,
                "assigned_to": None,
                "is_confidential": True,
            },
            verify_fields=("kind", "submitted_by", "person", "company", "title", "description", "is_confidential"),
        )

        from core.management.commands.demo_seed_support import seed_extended_fixtures

        extended = seed_extended_fixtures(
            record=record,
            users=users,
            company_a=company_a,
            company_b=company_b,
            insurer=insurer,
            employee_a=employee_a,
            employee_b=employee_b,
            created_counts=created_counts,
            reused_counts=reused_counts,
        )

        self.stdout.write(self.style.SUCCESS("داده‌های نمونه ایجاد/بازیابی شدند؛ هیچ رکورد موجودی بازنویسی نشد."))
        self.stdout.write(f"پوشش مدل‌ها: {extended['model_coverage']} از 45 مدل")
        self.stdout.write(f"رکوردهای نمونه ایجاد/بازیابی‌شده: {extended['fixture_rows']}")
        self.stdout.write(f"مجموع رکوردهای موجود در مدل‌های تحت پوشش: {extended['total_model_rows']}")
        self.stdout.write(
            "سناریوها: "
            f"{extended['service_requests']} درخواست، "
            f"{extended['claims']} خسارت، "
            f"{extended['assets']} دارایی، "
            f"{extended['documents']} سند و "
            f"{extended['work_delegations']} تفویض اختیار"
        )
        new_demo_users = list(generated_users) + list(extended["additional_users_created"])
        self.stdout.write("حساب‌های نمایشی: Admin, Shahamat, Salimi, Amiri, Delbari, Mahbod, "
                         "Namayande1 تا Namayande4، Saman و Saman2")
        self.stdout.write("رمز مشترک حساب‌های تازه‌ساخته‌شده از PRESENTATION_DEMO_PASSWORD خوانده شد.")
        self.stdout.write("این حساب‌ها فقط برای نمایش و آزمون هستند؛ پیش از استقرار واقعی غیرفعال/بازتنظیم شوند.")
        self.stdout.write("تعداد ایجادشده: " + str(sum(created_counts.values())))
        self.stdout.write("تعداد بازیابی‌شده بدون تغییر: " + str(sum(reused_counts.values())))
