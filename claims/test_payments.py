from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import RoleAssignment, User
from claims.models import Claim, ClaimPayment
from claims.services import record_imported_payment, record_payment, reverse_payment
from insurance.models import Insurer
from organizations.models import Company, Person


class ClaimPaymentLedgerTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="PAY-A", name="شرکت پرداخت")
        self.person = Person.objects.create(
            company=self.company,
            national_id="1111111111",
            first_name="کارمند",
            last_name="آزمایشی",
            birth_date=date(1990, 1, 1),
        )
        self.operator = self._user_with_role("payment-operator", RoleAssignment.Role.SYSTEM_ADMIN)
        self.reviewer = self._user_with_role("payment-reviewer", RoleAssignment.Role.DEPARTMENT_HEAD)
        self.claim = Claim.objects.create(
            claim_number="PAY-CLAIM-1",
            person=self.person,
            company_snapshot=self.company,
            service_type="خدمت آزمایشی",
            requested_amount=Decimal("1000"),
            assessed_amount=Decimal("800"),
            payable_amount=Decimal("800"),
        )

    def _user_with_role(self, username, role, *, insurer=None):
        user = User.objects.create_user(
            username=username,
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=user,
            role=role,
            insurer=insurer,
            reason="انتصاب در تست خودکار",
        )
        return user

    def test_payment_instalments_require_independent_approval_and_aggregate(self):
        first = record_payment(
            claim_id=self.claim.pk,
            amount="300",
            actor=self.operator,
            confirmed_by=self.reviewer,
            note="پرداخت اول",
        )
        second = record_payment(
            claim_id=self.claim.pk,
            amount="500",
            actor=self.operator,
            confirmed_by=self.reviewer,
            note="پرداخت دوم",
        )
        self.claim.refresh_from_db()
        self.assertEqual(first.entry_type, ClaimPayment.EntryType.PAYMENT)
        self.assertEqual(second.entry_type, ClaimPayment.EntryType.PAYMENT)
        self.assertEqual(self.claim.paid_amount, Decimal("800"))
        self.assertEqual(self.claim.status, Claim.Status.PAID)
        self.assertEqual(self.claim.payments.count(), 2)
        self.assertEqual(first.confirmed_by_id, self.reviewer.pk)

    def test_payment_cannot_exceed_payable_total(self):
        record_payment(
            claim_id=self.claim.pk, amount="700",
            actor=self.operator, confirmed_by=self.reviewer,
        )
        with self.assertRaises(ValidationError):
            record_payment(
                claim_id=self.claim.pk, amount="101",
                actor=self.operator, confirmed_by=self.reviewer,
            )

    def test_payment_rejects_missing_or_self_approval(self):
        with self.assertRaises(ValidationError):
            record_payment(claim_id=self.claim.pk, amount="100", actor=self.operator)
        with self.assertRaises(ValidationError):
            record_payment(
                claim_id=self.claim.pk, amount="100",
                actor=self.operator, confirmed_by=self.operator,
            )

    def test_correction_is_an_independent_approved_reversal(self):
        original = record_payment(
            claim_id=self.claim.pk, amount="400",
            actor=self.operator, confirmed_by=self.reviewer,
            note="پرداخت اولیه",
        )
        reversal = reverse_payment(
            payment_id=original.pk,
            amount="100",
            actor=self.operator,
            confirmed_by=self.reviewer,
            reason="اصلاح مبلغ اعلامی",
        )
        self.claim.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(self.claim.paid_amount, Decimal("300"))
        self.assertTrue(ClaimPayment.objects.filter(pk=original.pk).exists())
        self.assertEqual(reversal.entry_type, ClaimPayment.EntryType.REVERSAL)
        self.assertEqual(reversal.confirmed_by_id, self.reviewer.pk)

    def test_reversal_cannot_exceed_original_payment(self):
        original = record_payment(
            claim_id=self.claim.pk, amount="200",
            actor=self.operator, confirmed_by=self.reviewer,
        )
        with self.assertRaises(ValidationError):
            reverse_payment(
                payment_id=original.pk, amount="201",
                actor=self.operator, confirmed_by=self.reviewer,
                reason="مبلغ بیش از حد",
            )

    def test_payment_entry_cannot_be_updated_or_deleted(self):
        payment = record_payment(
            claim_id=self.claim.pk, amount="100",
            actor=self.operator, confirmed_by=self.reviewer,
        )
        payment.note = "ویرایش غیرمجاز"
        with self.assertRaises(ValidationError):
            payment.save()
        with self.assertRaises(ValidationError):
            payment.delete()
        with self.assertRaises(ValidationError):
            ClaimPayment.objects.filter(pk=payment.pk).update(note="تغییر گروهی غیرمجاز")
        with self.assertRaises(ValidationError):
            ClaimPayment.objects.filter(pk=payment.pk).delete()

    def test_insurer_reported_payment_requires_separate_internal_review(self):
        insurer = Insurer.objects.create(name="بیمه‌گر تست")
        self.claim.insurer = insurer
        self.claim.save()
        submitter = self._user_with_role(
            "insurer-reporter", RoleAssignment.Role.INSURER_REP, insurer=insurer,
        )
        payment = record_imported_payment(
            claim_id=self.claim.pk,
            amount="250",
            paid_at=date(2026, 11, 1),
            source_reference="VOUCHER-001",
            source_insurer=insurer,
            submitted_by=submitter,
            reviewed_by=self.reviewer,
        )
        self.claim.refresh_from_db()
        self.assertEqual(payment.recorded_by_id, submitter.pk)
        self.assertEqual(payment.confirmed_by_id, self.reviewer.pk)
        self.assertTrue(payment.is_legacy_import)
        self.assertEqual(self.claim.paid_amount, Decimal("250"))

    def test_insurer_cannot_approve_its_own_imported_payment(self):
        insurer = Insurer.objects.create(name="بیمه‌گر تست دوم")
        self.claim.insurer = insurer
        self.claim.save()
        submitter = self._user_with_role(
            "insurer-reporter-2", RoleAssignment.Role.INSURER_REP, insurer=insurer,
        )
        with self.assertRaises(ValidationError):
            record_imported_payment(
                claim_id=self.claim.pk,
                amount="100",
                paid_at=None,
                source_reference="VOUCHER-002",
                source_insurer=insurer,
                submitted_by=submitter,
                reviewed_by=submitter,
            )
