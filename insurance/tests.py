from datetime import date

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase

from accounts.models import RoleAssignment, User
from insurance.models import Contract, ContractRevision, Insurer, InsuranceLine


class ContractValidationTests(TestCase):
    def test_contract_end_date_cannot_precede_start_date(self):
        insurer = Insurer.objects.create(name="بیمه‌گر آزمایشی")
        with self.assertRaises(ValidationError):
            Contract.objects.create(
                code="CONTRACT-INVALID-DATES",
                title="قرارداد آزمایشی",
                insurer=insurer,
                line=InsuranceLine.HEALTH,
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 31),
            )

    def test_valid_contract_dates_are_accepted(self):
        insurer = Insurer.objects.create(name="بیمه‌گر معتبر")
        contract = Contract.objects.create(
            code="CONTRACT-VALID-DATES",
            title="قرارداد معتبر",
            insurer=insurer,
            line=InsuranceLine.HEALTH,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        self.assertEqual(contract.end_date, date(2026, 12, 31))


class InsuranceAdminBoundaryTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = User.objects.create_user(
            username="insurance-admin-unassigned",
            password="StrongPass!2026",
            is_staff=True,
            must_change_password=False,
        )
        self.operator = User.objects.create_user(
            username="insurance-admin-global",
            password="StrongPass!2026",
            is_staff=True,
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.operator,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه در آزمون مرز مدیریت بیمه",
        )

    def _request(self, user):
        request = self.factory.get("/admin/")
        request.user = user
        return request

    def test_contract_and_revision_admin_are_read_only_even_for_global_operator(self):
        request = self._request(self.operator)
        for model in (Contract, ContractRevision):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.has_module_permission(request))
                self.assertTrue(model_admin.has_view_permission(request))
                self.assertFalse(model_admin.has_add_permission(request))
                self.assertFalse(model_admin.has_change_permission(request))
                self.assertFalse(model_admin.has_delete_permission(request))

    def test_unassigned_staff_cannot_open_insurance_admin_modules(self):
        request = self._request(self.staff)
        for model in (Insurer, Contract, ContractRevision):
            model_admin = admin.site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_module_permission(request))
                self.assertFalse(model_admin.has_view_permission(request))

    def test_insurer_reference_can_be_managed_only_by_global_operator_and_never_deleted(self):
        global_request = self._request(self.operator)
        staff_request = self._request(self.staff)
        model_admin = admin.site._registry[Insurer]

        self.assertTrue(model_admin.has_add_permission(global_request))
        self.assertTrue(model_admin.has_change_permission(global_request))
        self.assertFalse(model_admin.has_delete_permission(global_request))
        self.assertFalse(model_admin.has_add_permission(staff_request))
        self.assertFalse(model_admin.has_change_permission(staff_request))
