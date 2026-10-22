from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from insurance.models import Contract, Insurer, InsuranceLine


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
