from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.access import company_ids_for, has_global_access, has_line_access, has_role, insurer_ids_for, is_company_representative, line_codes_for
from accounts.models import RoleAssignment, User
from insurance.models import Insurer
from organizations.models import Company


class ScopedRoleAssignmentTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="ASSIGN-A", name="شرکت الف")
        self.company_b = Company.objects.create(code="ASSIGN-B", name="شرکت ب")
        self.user = User.objects.create_user(
            username="multi-role-user",
            password="StrongPass!2026",
            role=User.Role.SUBSIDIARY_REP,
            company=self.company_a,
            must_change_password=False,
        )

    def make_assignment(self, **kwargs):
        defaults = {
            "user": self.user,
            "role": RoleAssignment.Role.SUBSIDIARY_REP,
            "company": self.company_a,
            "line_code": "*",
            "valid_from": timezone.localdate() - timedelta(days=1),
            "is_active": True,
            "reason": "تست",
        }
        defaults.update(kwargs)
        return RoleAssignment.objects.create(**defaults)

    def test_company_assignment_does_not_cross_company_boundary(self):
        self.make_assignment()
        self.assertTrue(is_company_representative(self.user, self.company_a.pk))
        self.assertFalse(is_company_representative(self.user, self.company_b.pk))

    def test_assignment_expiry_disables_legacy_role_fallback(self):
        assignment = self.make_assignment(
            is_active=False,
            valid_until=timezone.localdate() - timedelta(days=1),
        )
        self.assertFalse(has_role(
            self.user,
            RoleAssignment.Role.SUBSIDIARY_REP,
            company_id=self.company_a.pk,
        ))

    def test_specialist_line_scope_is_exact(self):
        specialist = User.objects.create_user(
            username="health-specialist",
            password="StrongPass!2026",
            role=User.Role.INSURANCE_SPECIALIST,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            valid_from=timezone.localdate() - timedelta(days=1),
            reason="تخصیص رشته درمان",
        )
        self.assertTrue(has_line_access(specialist, "health"))
        self.assertFalse(has_line_access(specialist, "third_party"))

    def test_system_admin_assignment_grants_global_access(self):
        admin_user = User.objects.create_user(
            username="assigned-system-admin",
            password="StrongPass!2026",
            role=User.Role.EMPLOYEE,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=admin_user,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            valid_from=timezone.localdate() - timedelta(days=1),
            reason="انتصاب مدیر سامانه",
        )
        self.assertTrue(has_global_access(admin_user))

    def test_superuser_is_system_admin_not_every_business_role(self):
        admin = User.objects.create_user(
            username="technical-superuser",
            password="StrongPass!2026",
            is_superuser=True,
            is_staff=True,
            must_change_password=False,
        )
        self.assertTrue(has_global_access(admin))
        self.assertTrue(has_role(admin, RoleAssignment.Role.SYSTEM_ADMIN))
        self.assertFalse(has_role(admin, RoleAssignment.Role.SUBSIDIARY_REP))
        self.assertFalse(has_role(admin, RoleAssignment.Role.INSURER_REP))
        self.assertFalse(has_role(admin, RoleAssignment.Role.INSURANCE_SPECIALIST))

    def test_insurer_assignment_is_bound_to_one_insurer(self):
        insurer_a = Insurer.objects.create(name="بیمه الف")
        insurer_b = Insurer.objects.create(name="بیمه ب")
        insurer_user = User.objects.create_user(
            username="insurer-rep",
            password="StrongPass!2026",
            role=User.Role.EMPLOYEE,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=insurer_user,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=insurer_a,
            valid_from=timezone.localdate() - timedelta(days=1),
            reason="نماینده بیمه‌گر",
        )
        self.assertTrue(has_role(
            insurer_user,
            RoleAssignment.Role.INSURER_REP,
            insurer_id=insurer_a.pk,
        ))
        self.assertFalse(has_role(
            insurer_user,
            RoleAssignment.Role.INSURER_REP,
            insurer_id=insurer_b.pk,
        ))


class InactiveAccountAuthorizationTests(TestCase):
    def test_inactive_superuser_cannot_use_global_role_bypass(self):
        inactive_admin = User.objects.create_user(
            username="inactive-superuser",
            password="StrongPass!2026",
            is_active=False,
            is_superuser=True,
            is_staff=True,
            must_change_password=False,
        )
        self.assertFalse(has_role(inactive_admin, RoleAssignment.Role.SYSTEM_ADMIN))
        self.assertFalse(has_global_access(inactive_admin))

    def test_inactive_account_has_no_scoped_company_insurer_or_line_data(self):
        company = Company.objects.create(code="INACTIVE-SCOPE", name="شرکت حساب غیرفعال")
        insurer = Insurer.objects.create(name="بیمه‌گر حساب غیرفعال")
        inactive_rep = User.objects.create_user(
            username="inactive-representative",
            password="StrongPass!2026",
            role=User.Role.SUBSIDIARY_REP,
            company=company,
            is_active=False,
            must_change_password=False,
        )
        inactive_insurer = User.objects.create_user(
            username="inactive-insurer",
            password="StrongPass!2026",
            role=User.Role.INSURER,
            insurer=insurer,
            is_active=False,
            must_change_password=False,
        )
        self.assertEqual(company_ids_for(inactive_rep), set())
        self.assertEqual(line_codes_for(inactive_rep), set())
        self.assertEqual(insurer_ids_for(inactive_insurer), set())
