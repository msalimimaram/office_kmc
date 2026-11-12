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
from workflow.models import WorkflowCase
from core.management.commands.seed_operational_workflows import Command as WorkflowSeedCommand


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
        workflow_owner = User.objects.create_user(
            username="import-workflow-owner",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=workflow_owner,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای انتشار گردش‌کارهای آزمون",
        )
        WorkflowSeedCommand().handle()
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
        self.assertTrue(WorkflowCase.objects.filter(
            definition__code="claim_review",
            object_id=str(claim.pk),
        ).exists())

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


class AssetImportApprovalSnapshotTests(TestCase):
    def test_asset_import_keeps_policy_and_valuation_snapshots_pending_until_approval(self):
        from datetime import timedelta
        from django.utils import timezone
        from assets.models import AssetPolicyPeriod, AssetValuation, InsuredAsset
        from insurance.models import Contract, Insurer, InsuranceLine
        from organizations.models import Company
        from imports.wizard import _process_assets_batch

        today = timezone.localdate()
        company = Company.objects.create(
            code="IMP-ASSET-SNAPSHOT",
            name="شرکت ورود دارایی",
        )
        insurer = Insurer.objects.create(name="بیمه‌گر ورود دارایی")
        contract = Contract.objects.create(
            code="IMP-ASSET-CONTRACT",
            title="قرارداد دارایی",
            insurer=insurer,
            line=InsuranceLine.FIRE,
            start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=305),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        contract.companies.add(company)

        uploader = User.objects.create_user(
            username="asset-import-uploader",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=uploader,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code=InsuranceLine.FIRE,
            reason="کارشناس رشته برای بارگذاری دارایی",
        )
        reviewer = User.objects.create_user(
            username="asset-import-reviewer",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=reviewer,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای تأیید ورود دارایی",
        )
        WorkflowSeedCommand().handle()

        batch = ImportBatch.objects.create(
            batch_number="IMP-ASSET-SNAPSHOT-001",
            file=SimpleUploadedFile("assets.xlsx", b"asset-import"),
            uploaded_by=uploader,
            status=ImportBatch.Status.VALIDATED,
            total_rows=1,
            valid_rows=1,
            invalid_rows=0,
            preview_data=[{
                "asset_code": "IMP-ASSET-001",
                "name": "تجهیزات واردشده",
                "asset_type": InsuredAsset.Type.EQUIPMENT,
                "owner_type": "company",
                "company_id": company.pk,
                "company_code": company.code,
                "person_id": None,
                "identifier": "EQ-IMP-001",
                "location": "سایت اصلی",
                "insured_value": "250000",
                "contract_id": contract.pk,
                "contract_number": contract.code,
                "insurer_id": insurer.pk,
                "policy_number": "IMP-POLICY-001",
                "policy_start": today.isoformat(),
                "policy_end": (today + timedelta(days=180)).isoformat(),
                "valuation_date": today.isoformat(),
                "market_value": "300000",
                "valuation_method": AssetValuation.Method.EXPERT,
                "plate_number": "",
                "vin": "",
                "engine_number": "",
                "make": "",
                "model_name": "",
                "model_year": None,
            }],
        )

        _process_assets_batch(batch, reviewer, None)

        asset = InsuredAsset.objects.get(asset_code="IMP-ASSET-001")
        valuation = AssetValuation.objects.get(asset=asset)
        period = AssetPolicyPeriod.objects.get(asset=asset)
        self.assertEqual(asset.insured_value, 0)
        self.assertIsNone(asset.insurer_id)
        self.assertIsNone(asset.contract_id)
        self.assertEqual(asset.policy_number, "")
        self.assertEqual(valuation.status, AssetValuation.Status.PENDING_APPROVAL)
        self.assertEqual(period.status, AssetPolicyPeriod.Status.PENDING_APPROVAL)
        self.assertEqual(
            WorkflowCase.objects.filter(object_id__in=[str(valuation.pk), str(period.pk)]).count(),
            2,
        )
