from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from imports.views import _parse_amount, _parse_date


class ClaimImportValidationTests(SimpleTestCase):
    def test_amount_accepts_decimal_and_thousands_separators(self):
        self.assertEqual(_parse_amount("1,250.75", 2, "paid_amount"), Decimal("1250.75"))

    def test_amount_accepts_persian_digits_and_decimal_separator(self):
        self.assertEqual(_parse_amount("۱٬۲۵۰٫۷۵", 2, "paid_amount"), Decimal("1250.75"))

    def test_amount_rejects_negative_values(self):
        with self.assertRaisesRegex(ValueError, "نامنفی"):
            _parse_amount("-1", 4, "paid_amount")

    def test_amount_rejects_nan_and_infinity(self):
        for value in ("NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _parse_amount(value, 3, "requested_amount")

    def test_empty_amount_defaults_to_zero(self):
        self.assertEqual(_parse_amount(None, 2, "paid_amount"), Decimal("0"))

    def test_amount_rejects_more_than_two_decimal_places(self):
        with self.assertRaisesRegex(ValueError, "۲ رقم اعشار"):
            _parse_amount("12.345", 2, "paid_amount")

    def test_amount_rejects_values_that_exceed_model_precision(self):
        with self.assertRaisesRegex(ValueError, "۱۴ رقم صحیح"):
            _parse_amount("100000000000000.00", 2, "requested_amount")

    def test_date_accepts_iso_date(self):
        self.assertEqual(_parse_date("2026-10-21", 2, "service_date"), date(2026, 10, 21))

    def test_date_accepts_jalali_date_with_persian_digits(self):
        self.assertEqual(_parse_date("۱۴۰۵/۰۸/۰۲", 2, "service_date"), date(2026, 10, 24))

    def test_date_accepts_excel_datetime(self):
        from datetime import datetime
        self.assertEqual(_parse_date(datetime(2026, 10, 21, 12, 30), 2, "service_date"), date(2026, 10, 21))

    def test_date_rejects_malformed_value_instead_of_silently_dropping_it(self):
        with self.assertRaisesRegex(ValueError, "معتبر نیست"):
            _parse_date("not-a-date", 8, "payment_date")


from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import RoleAssignment, User
from claims.models import Claim, ClaimPayment
from imports.models import ImportBatch
from insurance.models import Contract, Insurer, InsuranceLine
from organizations.models import Company, Person


class ImportBatchApprovalFlowTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="IMP-A", name="شرکت واردسازی")
        self.insurer = Insurer.objects.create(name="بیمه‌گر واردسازی")
        self.contract = Contract.objects.create(
            code="IMP-CONTRACT-1",
            title="قرارداد درمان واردسازی",
            insurer=self.insurer,
            line=InsuranceLine.HEALTH,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 29),
            is_active=True,
        )
        self.contract.companies.set([self.company])
        self.person = Person.objects.create(
            company=self.company,
            national_id="1234567890",
            first_name="کارمند",
            last_name="واردسازی",
            birth_date=date(1990, 1, 1),
        )
        self.insurer_user = User.objects.create_user(
            username="import-insurer", password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.insurer_user,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=self.insurer,
            reason="نماینده بیمه‌گر در تست واردسازی",
        )
        self.reviewer = User.objects.create_user(
            username="import-reviewer", password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.reviewer,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=InsuranceLine.HEALTH,
            reason="کارشناس درمان در تست واردسازی",
        )
        self.batch = ImportBatch.objects.create(
            batch_number="IMP-TEST-0001",
            file=SimpleUploadedFile("claims.xlsx", b"test-file"),
            uploaded_by=self.insurer_user,
            status=ImportBatch.Status.VALIDATED,
            total_rows=1,
            valid_rows=1,
            invalid_rows=0,
            preview_data=[{
                "claim_number": "IMP-TEST-CLAIM-0001",
                "source_claim_number": "INSURER-CLAIM-77",
                "person_id": self.person.pk,
                "primary_insured_id": self.person.pk,
                "company_snapshot_id": self.company.pk,
                "service_type": "ویزیت",
                "requested_amount": "500",
                "assessed_amount": "400",
                "payable_amount": "300",
                "paid_amount": "100",
                "service_date": "2026-10-20",
                "registered_date": "2026-10-22",
                "source_registered_date": "2026-10-22",
                "payment_date": "2026-10-30",
                "contract_id": self.contract.pk,
                "insurer_id": self.insurer.pk,
                "contract_number_snapshot": self.contract.code,
                "source_duplicate_status": Claim.DuplicateStatus.NOT_DECLARED,
                "source_duplicate_reference": "",
                "source_duplicate_note": "",
                "source_duplicate_reported_at": None,
                "source_reference": "claims.xlsx",
            }],
        )

    def test_insurer_cannot_approve_own_batch_but_specialist_can(self):
        client = Client()
        client.force_login(self.insurer_user)
        response = client.post(
            reverse("claim_import_confirm", args=[self.batch.pk]),
            {"review_note": "تلاش تأیید توسط بارگذار"},
        )
        self.assertEqual(response.status_code, 403)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ImportBatch.Status.VALIDATED)

        client.force_login(self.reviewer)
        response = client.post(
            reverse("claim_import_confirm", args=[self.batch.pk]),
            {"review_note": "بررسی و تأیید کارشناس درمان"},
        )
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ImportBatch.Status.PROCESSED)
        self.assertEqual(self.batch.reviewed_by_id, self.reviewer.pk)
        self.assertEqual(self.batch.preview_data, [])

        claim = Claim.objects.get(source_claim_number="INSURER-CLAIM-77")
        payment = ClaimPayment.objects.get(claim=claim)
        self.assertEqual(claim.company_snapshot_id, self.company.pk)
        self.assertEqual(claim.paid_amount, Decimal("100"))
        self.assertEqual(payment.recorded_by_id, self.insurer_user.pk)
        self.assertEqual(payment.confirmed_by_id, self.reviewer.pk)
        self.assertTrue(payment.is_legacy_import)

    def test_specialist_payment_import_requires_independent_head_review(self):
        batch = ImportBatch.objects.create(
            batch_number="IMP-TEST-0002",
            file=SimpleUploadedFile("specialist-claims.xlsx", b"test-file"),
            uploaded_by=self.reviewer,
            status=ImportBatch.Status.VALIDATED,
            total_rows=1,
            valid_rows=1,
            invalid_rows=0,
            preview_data=[dict(self.batch.preview_data[0])],
        )
        head = User.objects.create_user(
            username="import-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای بازبینی ورود داخلی",
        )
        client = Client()
        client.force_login(self.reviewer)
        self.assertEqual(
            client.post(reverse("claim_import_confirm", args=[batch.pk])).status_code,
            403,
        )

        client.force_login(head)
        response = client.post(reverse("claim_import_confirm", args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        claim = Claim.objects.get(source_claim_number="INSURER-CLAIM-77")
        payment = ClaimPayment.objects.get(claim=claim)
        self.assertEqual(payment.recorded_by_id, self.reviewer.pk)
        self.assertEqual(payment.confirmed_by_id, head.pk)
        self.assertEqual(payment.source_insurer_id, self.insurer.pk)
