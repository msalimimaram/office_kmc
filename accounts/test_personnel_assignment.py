from datetime import date

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    OrganizationalPosition,
    OrganizationalUnit,
    PositionAssignment,
    RoleAssignment,
    User,
)
from accounts.provisioning import provision_insured_person_account
from organizations.models import Company, Person, PersonEmployment


class InsuredPersonAccountProvisioningTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="IDENTITY-CO",
            name="شرکت آزمون هویت",
        )
        self.admin = User.objects.create_user(
            username="0000000001",
            password="09120000001",
            national_id="0000000001",
            mobile="09120000001",
            must_change_password=True,
        )
        RoleAssignment.objects.create(
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            valid_from=timezone.localdate(),
            reason="مدیر سامانه برای آزمون ایجاد حساب",
        )
        self.person = Person.objects.create(
            company=self.company,
            national_id="1234567890",
            first_name="کارمند",
            last_name="آزمایشی",
            birth_date=date(1990, 1, 1),
            mobile="09123456789",
            is_insured=True,
            is_active=True,
        )
        PersonEmployment.objects.create(
            person=self.person,
            company=self.company,
            personnel_code="T-100",
            valid_from=timezone.localdate(),
            status=PersonEmployment.Status.ACTIVE,
            created_by=self.admin,
            approved_by=self.admin,
        )

    def test_new_account_uses_national_id_and_hashed_mobile_then_forces_reset(self):
        user = provision_insured_person_account(
            self.person,
            company=self.company,
            actor=self.admin,
            source_reference="TEST-ROSTER",
        )

        self.assertEqual(user.username, self.person.national_id)
        self.assertEqual(user.national_id, self.person.national_id)
        self.assertEqual(user.mobile, self.person.mobile)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(self.person.mobile))
        self.assertNotEqual(user.password, self.person.mobile)
        self.assertEqual(self.person.__class__.objects.get(pk=self.person.pk).user_id, user.pk)
        self.assertTrue(RoleAssignment.objects.filter(
            user=user,
            role=RoleAssignment.Role.INSURED_PERSON,
            company=self.company,
            is_active=True,
        ).exists())

    def test_updating_mobile_does_not_reset_existing_password(self):
        user = provision_insured_person_account(
            self.person,
            company=self.company,
            actor=self.admin,
        )
        original_password_hash = user.password
        self.person.mobile = "09123456780"
        self.person.save(update_fields=["mobile", "updated_at"])

        updated_user = provision_insured_person_account(
            self.person,
            company=self.company,
            actor=self.admin,
        )

        self.assertEqual(updated_user.mobile, "09123456780")
        self.assertEqual(updated_user.password, original_password_hash)
        self.assertTrue(updated_user.check_password("09123456789"))
        self.assertFalse(updated_user.check_password("09123456780"))

    def test_invalid_mobile_prevents_account_creation(self):
        self.person.mobile = "12345"
        self.person.save(update_fields=["mobile", "updated_at"])

        with self.assertRaises(ValidationError):
            provision_insured_person_account(
                self.person,
                company=self.company,
                actor=self.admin,
            )
        self.assertFalse(User.objects.filter(username=self.person.national_id).exists())


class OrganizationalPositionCapacityTests(TestCase):
    def setUp(self):
        self.unit = OrganizationalUnit.objects.get(code="insurance-department")
        self.single_position = OrganizationalPosition.objects.get(
            unit=self.unit,
            code="health-supervisor",
        )
        self.multi_position = OrganizationalPosition.objects.get(
            unit=self.unit,
            code="health-specialist",
        )
        self.user_one = User.objects.create_user(
            username="1234567001",
            password="09123456701",
            national_id="1234567001",
            mobile="09123456701",
            must_change_password=True,
        )
        self.user_two = User.objects.create_user(
            username="1234567002",
            password="09123456702",
            national_id="1234567002",
            mobile="09123456702",
            must_change_password=True,
        )

    def test_single_holder_position_rejects_overlapping_second_person(self):
        PositionAssignment.objects.create(
            user=self.user_one,
            unit=self.unit,
            position=self.single_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="انتصاب اول برای آزمون",
        )
        with self.assertRaises(ValidationError):
            PositionAssignment.objects.create(
                user=self.user_two,
                unit=self.unit,
                position=self.single_position,
                line_code="health",
                valid_from=timezone.localdate(),
                reason="انتصاب دوم برای آزمون",
            )

    def test_specialist_position_allows_multiple_concurrent_holders(self):
        self.assertTrue(self.multi_position.allow_multiple_holders)
        first = PositionAssignment.objects.create(
            user=self.user_one,
            unit=self.unit,
            position=self.multi_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="کارشناس اول",
        )
        second = PositionAssignment.objects.create(
            user=self.user_two,
            unit=self.unit,
            position=self.multi_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="کارشناس دوم",
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_line_head_is_a_manager_only_in_its_line_scope(self):
        from accounts.access import is_unit_manager

        line_head = OrganizationalPosition.objects.get(
            unit=self.unit,
            code="health-head",
        )
        PositionAssignment.objects.create(
            user=self.user_one,
            unit=self.unit,
            position=line_head,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="رئیس رشته درمان",
        )
        self.assertTrue(is_unit_manager(self.user_one, line_code="health"))
        self.assertFalse(is_unit_manager(self.user_one, line_code="life"))

    def test_global_department_head_is_not_a_line_unit_manager(self):
        from accounts.access import is_unit_manager

        department_head = OrganizationalPosition.objects.get(
            unit=self.unit,
            code="department-head",
        )
        PositionAssignment.objects.create(
            user=self.user_one,
            unit=self.unit,
            position=department_head,
            line_code="",
            valid_from=timezone.localdate(),
            reason="رئیس اداره بیمه",
        )
        self.assertFalse(is_unit_manager(self.user_one))

    def test_global_department_head_role_cannot_be_attached_to_a_line_position(self):
        with self.assertRaises(ValidationError):
            RoleAssignment.objects.create(
                user=self.user_one,
                role=RoleAssignment.Role.DEPARTMENT_HEAD,
                organizational_unit=self.unit,
                position=self.single_position,
                line_code="health",
                valid_from=timezone.localdate(),
                reason="تطبیق نقش و سمت",
            )

    def test_role_assignment_path_cannot_bypass_existing_position_appointment(self):
        PositionAssignment.objects.create(
            user=self.user_one,
            unit=self.unit,
            position=self.single_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="انتصاب قبلی سازمانی",
        )
        with self.assertRaises(ValidationError):
            RoleAssignment.objects.create(
                user=self.user_two,
                role=RoleAssignment.Role.INSURANCE_SPECIALIST,
                organizational_unit=self.unit,
                position=self.single_position,
                line_code="health",
                valid_from=timezone.localdate(),
                reason="دسترسی دوم به سمت تک‌نفره",
            )

    def test_position_assignment_path_cannot_bypass_existing_access_assignment(self):
        RoleAssignment.objects.create(
            user=self.user_one,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            organizational_unit=self.unit,
            position=self.single_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="دسترسی قبلی سازمانی",
        )
        with self.assertRaises(ValidationError):
            PositionAssignment.objects.create(
                user=self.user_two,
                unit=self.unit,
                position=self.single_position,
                line_code="health",
                valid_from=timezone.localdate(),
                reason="انتصاب دوم در سمت تک‌نفره",
            )

    def test_role_assignment_admin_path_also_rejects_second_single_post_holder(self):
        RoleAssignment.objects.create(
            user=self.user_one,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            organizational_unit=self.unit,
            position=self.single_position,
            line_code="health",
            valid_from=timezone.localdate(),
            reason="دسترسی سرپرست اول",
        )
        with self.assertRaises(ValidationError):
            RoleAssignment.objects.create(
                user=self.user_two,
                role=RoleAssignment.Role.INSURANCE_SPECIALIST,
                organizational_unit=self.unit,
                position=self.single_position,
                line_code="health",
                valid_from=timezone.localdate(),
                reason="دسترسی سرپرست دوم",
            )


class PersonnelAssignmentViewTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="PERSONNEL-CO",
            name="شرکت آزمون انتصاب",
        )
        self.admin = User.objects.create_user(
            username="0000000002",
            password="Already-Changed-Admin-Password-2026!",
            national_id="0000000002",
            mobile="09120000002",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            valid_from=timezone.localdate(),
            reason="مدیر سامانه برای آزمون انتصاب",
        )
        self.person = Person.objects.create(
            company=self.company,
            national_id="1234567891",
            first_name="کارشناس",
            last_name="درمان",
            birth_date=date(1991, 2, 2),
            mobile="09123456781",
            is_insured=True,
            is_active=True,
        )
        PersonEmployment.objects.create(
            person=self.person,
            company=self.company,
            personnel_code="P-101",
            valid_from=timezone.localdate(),
            status=PersonEmployment.Status.ACTIVE,
            created_by=self.admin,
            approved_by=self.admin,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_system_admin_can_assign_roster_person_to_position_and_get_access(self):
        unit = OrganizationalUnit.objects.get(code="insurance-department")
        position = OrganizationalPosition.objects.get(unit=unit, code="health-supervisor")
        response = self.client.post(
            reverse("personnel_assignments"),
            {
                "action": "assign",
                "national_id": self.person.national_id,
                "position": position.pk,
                "line_code": "health",
                "valid_from": timezone.localdate().isoformat(),
                "valid_until": "",
                "reason": "انتصاب سرپرست درمان",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username=self.person.national_id)
        self.assertEqual(self.person.__class__.objects.get(pk=self.person.pk).user_id, user.pk)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(self.person.mobile))
        self.assertTrue(PositionAssignment.objects.filter(
            user=user, position=position, is_active=True
        ).exists())
        self.assertTrue(RoleAssignment.objects.filter(
            user=user,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            position=position,
            line_code="health",
            is_active=True,
        ).exists())

    def test_non_system_admin_cannot_open_personnel_assignment_page(self):
        ordinary = User.objects.create_user(
            username="1234567003",
            password="Already-Changed-User-Password-2026!",
            national_id="1234567003",
            mobile="09123456703",
            must_change_password=False,
        )
        client = Client(raise_request_exception=False)
        client.force_login(ordinary)
        response = client.get(reverse("personnel_assignments"))
        self.assertEqual(response.status_code, 403)
