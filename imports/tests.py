from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from imports.views import _parse_amount, _parse_date


class ClaimImportValidationTests(SimpleTestCase):
    def test_amount_accepts_decimal_and_thousands_separators(self):
        self.assertEqual(_parse_amount("1,250.75", 2, "paid_amount"), Decimal("1250.75"))

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

    def test_date_accepts_excel_datetime(self):
        from datetime import datetime
        self.assertEqual(_parse_date(datetime(2026, 10, 21, 12, 30), 2, "service_date"), date(2026, 10, 21))

    def test_date_rejects_malformed_value_instead_of_silently_dropping_it(self):
        with self.assertRaisesRegex(ValueError, "معتبر نیست"):
            _parse_date("not-a-date", 8, "payment_date")
