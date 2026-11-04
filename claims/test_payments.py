from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from claims.models import Claim, ClaimPayment
from claims.services import record_payment, reverse_payment
from organizations.models import Company, Person


class ClaimPaymentLedgerTests(TestCase):
    def setUp(self):
        company = Company.objects.create(code="PAY-A", name="شرکت پرداخت")
        person = Person.objects.create(
            company=company,
            national_id="1" * 10,
            first_name="کارمند",
            last_name="آزمایشی",
            birth_date=__import__("datetime").date(1990, 1, 1),
        )
        self.actor = User.objects.create_user(
            username="payment-operator",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.claim = Claim.objects.create(
            claim_number="PAY-CLAIM-1",
            person=person,
            company_snapshot=company,
            service_type="خدمت آزمایشی",
            requested_amount=Decimal("1000"),
            assessed_amount=Decimal("800"),
            payable_amount=Decimal("800"),
        )

    def test_payment_instalments_are_independent_and_aggregate(self):
        first = record_payment(
            claim_id=self.claim.pk,
            amount="300",
            actor=self.actor,
            note="پرداخت اول",
        )
        second = record_payment(
            claim_id=self.claim.pk,
            amount="500",
            actor=self.actor,
            note="پرداخت دوم",
        )
        self.claim.refresh_from_db()
        self.assertEqual(first.entry_type, ClaimPayment.EntryType.PAYMENT)
        self.assertEqual(second.entry_type, ClaimPayment.EntryType.PAYMENT)
        self.assertEqual(self.claim.paid_amount, Decimal("800"))
        self.assertEqual(self.claim.status, Claim.Status.PAID)
        self.assertEqual(self.claim.payments.count(), 2)

    def test_payment_cannot_exceed_payable_total(self):
        record_payment(claim_id=self.claim.pk, amount="700", actor=self.actor)
        with self.assertRaises(ValidationError):
            record_payment(claim_id=self.claim.pk, amount="101", actor=self.actor)

    def test_correction_is_a_reversal_and_original_payment_remains(self):
        original = record_payment(
            claim_id=self.claim.pk,
            amount="400",
            actor=self.actor,
            note="پرداخت اولیه",
        )
        reversal = reverse_payment(
            payment_id=original.pk,
            amount="100",
            actor=self.actor,
            reason="اصلاح مبلغ اعلامی",
        )
        self.claim.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(self.claim.paid_amount, Decimal("300"))
        self.assertTrue(ClaimPayment.objects.filter(pk=original.pk).exists())
        self.assertEqual(reversal.entry_type, ClaimPayment.EntryType.REVERSAL)

    def test_payment_entry_cannot_be_updated_or_deleted(self):
        payment = record_payment(claim_id=self.claim.pk, amount="100", actor=self.actor)
        payment.note = "ویرایش غیرمجاز"
        with self.assertRaises(ValidationError):
            payment.save()
        with self.assertRaises(ValidationError):
            payment.delete()
