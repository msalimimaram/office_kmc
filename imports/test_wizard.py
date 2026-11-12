from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from assets.models import AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle
from insurance.models import Contract, Insurer, InsuranceLine
from accounts.models import RoleAssignment, User
from imports.models import ImportBatch
from organizations.models import Company, Person, PersonEmployment


@override_settings(DEBUG=True, CLAMD_HOST="")
class FlexiblePeopleRosterImportTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="XLS-A", name="شرکت نمونه Excel الف")
        self.company_b = Company.objects.create(code="XLS-B", name="شرکت نمونه Excel ب")
        self.representative = User.objects.create_user(
            username="excel-company-rep", password="StrongPass!2026",
            must_change_password=False
        )
        RoleAssignment.objects.create(
            user=self.representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            line_code="*",
            reason="نماینده شرکت برای آزمون ورود گروهی",
        )
        self.reviewer = User.objects.create_user(
            username="excel-reviewer", password="StrongPass!2026",
            must_change_password=False
        )
        RoleAssignment.objects.create(
            user=self.reviewer,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای تأیید مستقل فایل",
        )

    def _workbook_upload(self, rows, name="roster.xlsx"):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([f"source_{index}" for index in range(1, 26)])
        for row in rows:
            sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return SimpleUploadedFile(
            name,
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _mapping(self):
        return {
            "column_action": "A",
            "column_national_id": "D",
            "column_first_name": "Y",
            "column_last_name": "X",
            "column_birth_date": "W",
            "column_personnel_code": "V",
            "column_mobile": "U",
            "column_iban": "T",
            "column_relationship": "S",
            "column_employee_national_id": "R",
            "column_company_code": "Q",
        }

    def _row(self, *, company_code="XLS-A", national_id="0012345678"):
        row = [None] * 25
        row[0] = "add_employee"
        row[3] = national_id
        row[22] = company_code
        row[20] = "09120000001"
        row[21] = "XLS-1001"
        row[23] = "کارمند"
        row[24] = "آزمایشی"
        row[22] = company_code
        row[21] = "XLS-1001"
        row[20] = "09120000001"
        row[19] = ""
        row[18] = ""
        row[17] = ""
        row[16] = company_code
        row[24] = "علی"
        row[23] = "نمونه"
        row[22] = "1988-05-12"
        row[21] = "XLS-1001"
        row[20] = "09120000001"
        row[19] = ""
        row[18] = ""
        row[17] = ""
        row[16] = company_code
        return row

    def _dependent_row(self, *, national_id="0012345691", employee_national_id="0012345690"):
        row = [None] * 25
        row[0] = "add_dependent"
        row[3] = national_id
        row[24] = "سارا"
        row[23] = "نمونه"
        row[22] = "1990-08-04"
        row[21] = "XLS-1001-01"
        row[20] = "09120000002"
        row[18] = "spouse"
        row[17] = employee_national_id
        row[16] = "XLS-A"
        return row

    def test_custom_column_mapping_supports_d_and_y_and_requires_independent_approval(self):
        client = self.client
        client.force_login(self.representative)
        response = client.post(
            reverse("people_import"),
            {"header_row": 1, **self._mapping(), "file": self._workbook_upload([self._row()])},
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(source_type="people_roster")
        self.assertEqual(batch.valid_rows, 1)
        self.assertEqual(batch.invalid_rows, 0)
        self.assertEqual(batch.column_mapping["national_id"], "D")
        self.assertEqual(batch.column_mapping["first_name"], "Y")
        self.assertEqual(Person.objects.filter(national_id="0012345678").count(), 0)

        # The uploader cannot approve their own import.
        self.assertEqual(
            client.post(reverse("profile_import_confirm", args=[batch.pk])).status_code,
            403,
        )
        client.force_login(self.reviewer)
        response = client.post(reverse("profile_import_confirm", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        person = Person.objects.get(national_id="0012345678")
        self.assertEqual(person.company_id, self.company_a.pk)
        self.assertEqual(person.first_name, "علی")
        self.assertEqual(person.last_name, "نمونه")
        employment = PersonEmployment.objects.get(person=person, company=self.company_a)
        self.assertEqual(employment.status, PersonEmployment.Status.ACTIVE)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.PROCESSED)
        self.assertEqual(batch.preview_data, [])

    def test_company_representative_cannot_import_people_for_another_company(self):
        row = self._row(company_code="XLS-B", national_id="0012345679")
        self.client.force_login(self.representative)
        response = self.client.post(
            reverse("people_import"),
            {"header_row": 1, **self._mapping(), "file": self._workbook_upload([row])},
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(source_type="people_roster")
        self.assertEqual(batch.valid_rows, 0)
        self.assertEqual(batch.invalid_rows, 1)
        self.assertFalse(Person.objects.filter(national_id="0012345679").exists())

    def test_visible_sample_page_shows_accepted_fields_and_rows(self):
        self.client.force_login(self.representative)
        response = self.client.get(reverse("import_sample", args=["people_roster"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "کد ملی شخص")
        self.assertContains(response, "0012345690")
        self.assertContains(response, "ستون نمونه")

    def test_template_is_available_to_authorized_company_representative(self):
        self.client.force_login(self.representative)
        response = self.client.get(reverse("import_template", args=["people_roster"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_uploader_role_is_rechecked_before_confirmation(self):
        row = self._row(national_id="0012345681")
        self.client.force_login(self.representative)
        self.client.post(
            reverse("people_import"),
            {"header_row": 1, **self._mapping(), "file": self._workbook_upload([row])},
        )
        batch = ImportBatch.objects.get(source_type="people_roster")
        assignment = self.representative.role_assignments.get(role=RoleAssignment.Role.SUBSIDIARY_REP)
        assignment.is_active = False
        assignment.save(update_fields=["is_active"])
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse("profile_import_confirm", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Person.objects.filter(national_id="0012345681").exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.VALIDATED)

    def test_primary_employee_and_dependent_can_be_imported_from_one_workbook(self):
        self.client.force_login(self.representative)
        response = self.client.post(
            reverse("people_import"),
            {
                "header_row": 1,
                **self._mapping(),
                "file": self._workbook_upload([
                    self._row(national_id="0012345690"),
                    self._dependent_row(),
                ]),
            },
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(source_type="people_roster")
        self.assertEqual(batch.valid_rows, 2)
        self.assertEqual(batch.invalid_rows, 0)

        self.client.force_login(self.reviewer)
        response = self.client.post(reverse("profile_import_confirm", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        primary = Person.objects.get(national_id="0012345690")
        dependent = Person.objects.get(national_id="0012345691")
        self.assertEqual(dependent.employee_id, primary.pk)
        self.assertEqual(dependent.company_id, self.company_a.pk)
        self.assertTrue(PersonEmployment.objects.filter(
            person=primary, company=self.company_a, status=PersonEmployment.Status.ACTIVE
        ).exists())


@override_settings(DEBUG=True, CLAMD_HOST="")
class SpecialistAssetImportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="AST-XLS-A", name="شرکت نمونه دارایی")
        self.insurer = Insurer.objects.create(name="بیمه‌گر نمونه دارایی")
        self.contract = Contract.objects.create(
            code="AST-XLS-BODY-01",
            title="قرارداد بدنه نمونه",
            insurer=self.insurer,
            line=InsuranceLine.BODY,
            start_date=date(2026, 1, 1),
            end_date=date(2028, 12, 29),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.contract.companies.set([self.company])

        self.specialist = User.objects.create_user(
            username="asset-body-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=InsuranceLine.BODY,
            reason="کارشناس بدنه برای آزمون ورود دارایی",
        )
        self.reviewer = User.objects.create_user(
            username="asset-import-reviewer",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.reviewer,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای تأیید مستقل ورود دارایی",
        )

    def _asset_row(self, *, asset_code="AST-XLS-VEH-001", contract_number=None):
        return [
            asset_code,
            "خودروی سازمانی نمونه",
            "vehicle",
            "company",
            self.company.code,
            "",
            "AST-REG-001",
            "پارکینگ شرکت",
            7500000000,
            contract_number or self.contract.code,
            "AST-POL-001",
            "2026-11-15",
            "2027-11-14",
            "2026-11-10",
            7600000000,
            "formal",
            "ایران 11-123 الف",
            "AST-VIN-001",
            "AST-ENG-001",
            "سازنده نمونه",
            "مدل آزمایشی",
            2024,
        ]

    def _asset_upload(self, row):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([f"source_{index}" for index in range(1, 23)])
        sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        return SimpleUploadedFile(
            "assets.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def _asset_post_data(self, row):
        from openpyxl.utils import get_column_letter
        from imports.profiles import PROFILES

        data = {"header_row": 1, "file": self._asset_upload(row)}
        for index, (key, _label, _default, _required) in enumerate(PROFILES["assets"]["fields"], start=1):
            data[f"column_{key}"] = get_column_letter(index)
        return data

    def test_asset_import_creates_vehicle_and_pending_approval_workflows(self):
        from core.management.commands.seed_operational_workflows import Command as WorkflowSeedCommand
        from workflow.models import WorkflowCase

        WorkflowSeedCommand().handle()
        self.client.force_login(self.specialist)
        response = self.client.post(
            reverse("asset_import"),
            self._asset_post_data(self._asset_row()),
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(source_type="assets")
        self.assertEqual(batch.valid_rows, 1)
        self.assertEqual(batch.invalid_rows, 0)
        self.assertEqual(InsuredAsset.objects.filter(asset_code="AST-XLS-VEH-001").count(), 0)

        self.client.force_login(self.reviewer)
        response = self.client.post(reverse("profile_import_confirm", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)

        asset = InsuredAsset.objects.get(asset_code="AST-XLS-VEH-001")
        vehicle = Vehicle.objects.get(asset=asset)
        self.assertEqual(vehicle.plate_number, "ایران 11-123 الف")
        valuation = AssetValuation.objects.get(asset=asset)
        policy_period = AssetPolicyPeriod.objects.get(asset=asset)
        self.assertEqual(valuation.status, AssetValuation.Status.PENDING_APPROVAL)
        self.assertEqual(policy_period.status, AssetPolicyPeriod.Status.PENDING_APPROVAL)
        self.assertTrue(WorkflowCase.objects.filter(
            definition__code="asset_valuation_approval",
            object_id=str(valuation.pk),
        ).exists())
        self.assertTrue(WorkflowCase.objects.filter(
            definition__code="asset_policy_approval",
            object_id=str(policy_period.pk),
        ).exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, ImportBatch.Status.PROCESSED)

    def test_asset_specialist_cannot_import_outside_assigned_insurance_line(self):
        health_user = User.objects.create_user(
            username="asset-health-only",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=health_user,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس درمان بدون اختیار رشته اموال",
        )
        self.client.force_login(health_user)
        response = self.client.post(
            reverse("asset_import"),
            self._asset_post_data(self._asset_row(asset_code="AST-XLS-OUT-001")),
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get(source_type="assets")
        self.assertEqual(batch.valid_rows, 0)
        self.assertEqual(batch.invalid_rows, 1)
        self.assertFalse(InsuredAsset.objects.filter(asset_code="AST-XLS-OUT-001").exists())
