from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import RoleAssignment, User
from claims.models import Claim, ClaimPayment
from insurance.models import Contract, Insurer, InsuranceLine
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest


class Command(BaseCommand):
    help = "ایجاد داده نمونه برای تست محلی سامانه؛ فقط در DEBUG مجاز است."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo فقط در محیط DEBUG قابل اجراست.")

        today = timezone.localdate()
        company_a, _ = Company.objects.update_or_create(
            code="DEMO-A", defaults={"name": "شرکت نمونه الف", "is_parent": True, "is_active": True}
        )
        company_b, _ = Company.objects.update_or_create(
            code="DEMO-B", defaults={"name": "شرکت نمونه ب", "is_parent": False, "is_active": True}
        )
        insurer, _ = Insurer.objects.update_or_create(name="بیمه‌گر نمونه", defaults={"is_active": True})
        contract, _ = Contract.objects.update_or_create(
            code="DEMO-1405",
            defaults={
                "title": "قرارداد نمونه درمان تکمیلی",
                "insurer": insurer,
                "line": InsuranceLine.HEALTH,
                "start_date": today.replace(month=1, day=1),
                "end_date": today.replace(month=12, day=29),
                "is_active": True,
            },
        )
        contract.companies.set([company_a, company_b])

        employee_a, _ = Person.objects.update_or_create(
            company=company_a, national_id="0012345678",
            defaults={"personnel_code":"A-1001", "first_name":"علی", "last_name":"نمونه", "birth_date":date(1988, 5, 12), "relationship":"employee", "is_insured":True, "is_active":True},
        )
        Person.objects.update_or_create(
            company=company_a, national_id="0012345679",
            defaults={"personnel_code":"A-1001-01", "first_name":"سارا", "last_name":"نمونه", "birth_date":date(1990, 8, 4), "relationship":"spouse", "employee":employee_a, "is_insured":True, "is_active":True},
        )
        employee_b, _ = Person.objects.update_or_create(
            company=company_b, national_id="0098765432",
            defaults={"personnel_code":"B-2001", "first_name":"رضا", "last_name":"آزمایشی", "birth_date":date(1985, 3, 22), "relationship":"employee", "is_insured":True, "is_active":True},
        )

        for username, role, company, national_id, insurer_obj in [
            ("admin.demo", User.Role.SYSTEM_ADMIN, None, "", None),
            ("head.demo", User.Role.DEPARTMENT_HEAD, None, "", None),
            ("specialist.demo", User.Role.INSURANCE_SPECIALIST, None, "", None),
            ("companya.demo", User.Role.SUBSIDIARY_REP, company_a, "", None),
            ("companyb.demo", User.Role.SUBSIDIARY_REP, company_b, "", None),
            ("employee.a", User.Role.EMPLOYEE, company_a, employee_a.national_id, None),
            ("employee.b", User.Role.EMPLOYEE, company_b, employee_b.national_id, None),
            ("insurer.demo", User.Role.INSURER, None, "", insurer),
        ]:
            user, created = User.objects.get_or_create(username=username, defaults={"role":role})
            user.role = role
            user.company = company
            user.national_id = national_id
            user.insurer = insurer_obj
            user.is_active = True
            user.must_change_password = False
            user.set_password("DemoPass!2026")
            user.save()

            assignment_role = {
                User.Role.SYSTEM_ADMIN: RoleAssignment.Role.SYSTEM_ADMIN,
                User.Role.DEPARTMENT_HEAD: RoleAssignment.Role.DEPARTMENT_HEAD,
                User.Role.INSURANCE_SPECIALIST: RoleAssignment.Role.INSURANCE_SPECIALIST,
                User.Role.SUBSIDIARY_REP: RoleAssignment.Role.SUBSIDIARY_REP,
                User.Role.EMPLOYEE: RoleAssignment.Role.INSURED_PERSON,
                User.Role.INSURER: RoleAssignment.Role.INSURER_REP,
            }[role]
            assignment_company = company if role in {User.Role.SUBSIDIARY_REP, User.Role.EMPLOYEE} else None
            assignment_insurer = insurer_obj if role == User.Role.INSURER else None
            assignment_line = (
                "health" if role == User.Role.INSURANCE_SPECIALIST else
                "*" if role in {User.Role.SUBSIDIARY_REP, User.Role.EMPLOYEE} else ""
            )
            RoleAssignment.objects.update_or_create(
                user=user,
                role=assignment_role,
                company=assignment_company,
                insurer=assignment_insurer,
                line_code=assignment_line,
                defaults={
                    "valid_from": today.replace(month=1, day=1),
                    "valid_until": None,
                    "is_active": True,
                    "reason": "انتصاب داده نمونه",
                },
            )

        Claim.objects.update_or_create(
            claim_number="DEMO-CLM-001",
            defaults={
                "person": employee_a, "contract": contract, "insurer": insurer,
                "service_date": today, "registered_date": today,
                "service_type":"نمونه خدمات درمانی", "requested_amount":Decimal("10000000"),
                "assessed_amount":Decimal("8000000"), "payable_amount":Decimal("8000000"),
                "paid_amount":Decimal("0"), "status":Claim.Status.APPROVED,
                "source_reference":"DEMO", "assessment_note":"داده آزمایشی",
            },
        )
        claim_b, _ = Claim.objects.update_or_create(
            claim_number="DEMO-CLM-002",
            defaults={
                "person": employee_b, "contract": contract, "insurer": insurer,
                "service_date": today, "registered_date": today,
                "service_type":"نمونه خسارت شرکت ب", "requested_amount":Decimal("5000000"),
                "assessed_amount":Decimal("5000000"), "payable_amount":Decimal("5000000"),
                "paid_amount":Decimal("5000000"), "payment_date":today,
                "status":Claim.Status.PAID, "source_reference":"DEMO",
            },
        )

        insurer_user = User.objects.get(username="insurer.demo")
        head_user = User.objects.get(username="head.demo")
        ClaimPayment.objects.get_or_create(
            claim=claim_b,
            is_legacy_import=True,
            defaults={
                "entry_type": ClaimPayment.EntryType.PAYMENT,
                "amount": Decimal("5000000"),
                "paid_at": today,
                "source_reference": "DEMO-VOUCHER-002",
                "source_insurer": insurer,
                "recorded_by": insurer_user,
                "confirmed_by": head_user,
                "note": "پرداخت نمونه منتقل‌شده از منبع؛ صرفاً سابقه اطلاعاتی و بدون انتقال وجه.",
            },
        )

        employee_user = User.objects.get(username="employee.a")
        ServiceRequest.objects.update_or_create(
            reference="IB-DEMO-001",
            defaults={
                "kind":ServiceRequest.Kind.DOCUMENT_REQUEST, "submitted_by":employee_user,
                "person":employee_a, "company":company_a, "title":"درخواست نمونه مدارک",
                "description":"درخواست آزمایشی برای تست گردش کار", "status":ServiceRequest.Status.SUBMITTED,
                "assigned_to":None, "is_confidential":False,
            },
        )
        ServiceRequest.objects.update_or_create(
            reference="IB-DEMO-002",
            defaults={
                "kind":ServiceRequest.Kind.MEDICAL_ASSISTANCE, "submitted_by":employee_user,
                "person":employee_a, "company":company_a, "title":"درخواست محرمانه نمونه",
                "description":"درخواست محرمانه آزمایشی", "status":ServiceRequest.Status.SUBMITTED,
                "assigned_to":None, "is_confidential":True,
            },
        )

        self.stdout.write(self.style.SUCCESS("داده نمونه ایجاد شد. رمز مشترک محلی حساب‌های نمونه: DemoPass!2026 — فقط در DEBUG و فقط با داده ساختگی استفاده شود."))
