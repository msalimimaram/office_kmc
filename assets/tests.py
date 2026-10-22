from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from organizations.models import Company
from assets.models import InsuredAsset


class AssetScopeTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="AS-A", name="شرکت الف")
        self.company_b = Company.objects.create(code="AS-B", name="شرکت ب")
        self.rep = User.objects.create_user(
            username="asset-rep", password="StrongPass!2026", must_change_password=False,
            role="subsidiary_rep", company=self.company_a,
        )
        InsuredAsset.objects.create(
            asset_code="ASSET-A1", name="خودروی شرکت الف",
            asset_type=InsuredAsset.Type.VEHICLE, company=self.company_a,
            created_by=self.rep,
        )
        InsuredAsset.objects.create(
            asset_code="ASSET-B1", name="دارایی شرکت ب",
            asset_type=InsuredAsset.Type.PROPERTY, company=self.company_b,
            created_by=self.rep,
        )

    def test_company_representative_sees_only_own_company_assets(self):
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("asset_list"))
        self.assertContains(response, "ASSET-A1")
        self.assertNotContains(response, "ASSET-B1")

    def test_company_representative_cannot_choose_another_company(self):
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("asset_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "AS-B")

    def test_asset_rejects_negative_insured_value_and_invalid_policy_dates(self):
        from datetime import date
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            InsuredAsset.objects.create(
                asset_code="ASSET-NEG", name="دارایی نامعتبر",
                asset_type=InsuredAsset.Type.PROPERTY, company=self.company_a,
                created_by=self.rep, insured_value=-1,
            )
        with self.assertRaises(ValidationError):
            InsuredAsset.objects.create(
                asset_code="ASSET-DATES", name="دارایی با تاریخ نامعتبر",
                asset_type=InsuredAsset.Type.PROPERTY, company=self.company_a,
                created_by=self.rep, policy_start=date(2026, 2, 1),
                policy_end=date(2026, 1, 1),
            )
