from datetime import date
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from accounts.models import RoleAssignment, User
from imports.models import ImportBatch
from organizations.models import Company, Person, PersonEmployment


class FlexiblePeopleRosterImportTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="XLS-A", name="شرکت نمونه Excel الف")
        self.company_b = Company.objects.create(code="XLS-B", name="شرکت نمونه Excel ب")
        self.representative = User.objects.create_user(
            username="excel-company-rep", password="StrongPass!2026"
        )
        RoleAssignment.objects.create(
            user=self.representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            line_code="*",
            reason="نماینده شرکت برای آزمون ورود گروهی",
        )
        self.reviewer = User.objects.create_user(
            username="excel-reviewer", password="StrongPass!2026"
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
