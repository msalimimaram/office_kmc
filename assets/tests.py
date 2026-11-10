from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import RoleAssignment, User
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
        RoleAssignment.objects.create(
            user=self.rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            line_code="*",
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

    def test_company_representative_cannot_create_or_choose_another_company_asset(self):
        client = Client()
        client.force_login(self.rep)
        response = client.get(reverse("asset_create"))
        # Asset registration is reserved for insurance specialists; a company
        # representative cannot bypass that policy by manipulating company ids.
        self.assertEqual(response.status_code, 403)

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



@override_settings(DEBUG=True, CLAMD_HOST="")
class AssetOperationalWorkflowTests(TestCase):
    def setUp(self):
        from datetime import date
        from accounts.models import RoleAssignment
        from insurance.models import Contract, Insurer
        from assets.models import Vehicle

        self.company = Company.objects.create(code="AS-OPS", name="شرکت عملیات دارایی")
        self.insurer = Insurer.objects.create(name="بیمه‌گر عملیات دارایی")
        self.specialist = User.objects.create_user(
            username="asset-ops-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="third_party",
            reason="کارشناس خودرو برای آزمون عملیات دارایی",
        )
        self.contract = Contract.objects.create(
            code="AS-OPS-CONTRACT",
            title="قرارداد خودرو",
            insurer=self.insurer,
            line="third_party",
            start_date=date(2026, 1, 1),
            end_date=date(2027, 1, 1),
        )
        self.contract.companies.add(self.company)
        self.asset = InsuredAsset.objects.create(
            asset_code="AS-OPS-1",
            name="خودروی عملیاتی",
            asset_type=InsuredAsset.Type.VEHICLE,
            company=self.company,
            insurer=self.insurer,
            contract=self.contract,
            policy_number="BASE-POLICY-1",
            policy_start=date(2026, 1, 1),
            policy_end=date(2027, 1, 1),
            created_by=self.specialist,
        )
        Vehicle.objects.create(
            asset=self.asset,
            plate_number="12الف345",
            vin="VIN-AS-OPS-1",
            make="سازنده",
            model_name="مدل",
            model_year=2024,
        )

        from workflow.models import WorkflowDefinition, WorkflowStep, WorkflowTransition
        from accounts.models import RoleAssignment

        self.head = User.objects.create_user(
            username="asset-approval-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.admin = User.objects.create_superuser(
            username="asset-approval-admin",
            email="asset-approval-admin@example.invalid",
            password="StrongPass!2026",
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای آزمون تأیید دارایی",
        )
        for workflow_code in (
            "asset_valuation_approval",
            "asset_policy_approval",
            "asset_endorsement_approval",
        ):
            self._create_asset_approval_workflow(
                workflow_code,
                WorkflowDefinition,
                WorkflowStep,
                WorkflowTransition,
                RoleAssignment,
            )

    def _create_asset_approval_workflow(
        self, code, WorkflowDefinition, WorkflowStep, WorkflowTransition, RoleAssignment
    ):
        definition = WorkflowDefinition.objects.create(
            code=code,
            title=f"گردش تأیید {code}",
            created_by=self.admin,
        )
        roles = [RoleAssignment.Role.DEPARTMENT_HEAD, RoleAssignment.Role.SYSTEM_ADMIN]
        pending = WorkflowStep.objects.create(
            definition=definition,
            code="pending_approval",
            title="در انتظار تأیید",
            order=1,
            allowed_roles=roles,
            is_initial=True,
        )
        approved = WorkflowStep.objects.create(
            definition=definition,
            code="approved",
            title="تأییدشده",
            order=2,
            allowed_roles=roles,
        )
        rejected = WorkflowStep.objects.create(
            definition=definition,
            code="rejected",
            title="ردشده",
            order=3,
            allowed_roles=roles,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=pending,
            target_step=approved,
            action_code="approve",
            title="تأیید",
            allowed_roles=roles,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=pending,
            target_step=rejected,
            action_code="reject",
            title="رد",
            allowed_roles=roles,
            requires_note=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=approved,
            action_code="finalize",
            title="ثبت نهایی",
            allowed_roles=roles,
            closes_case=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=rejected,
            action_code="finalize-rejection",
            title="ثبت نهایی رد",
            allowed_roles=roles,
            closes_case=True,
        )
        definition.approved_by = self.admin
        definition.is_active = True
        definition.save()

    def test_specialist_can_open_asset_detail_and_add_immutable_valuation_record(self):
        from auditlog.models import AuditEvent
        from django.core.exceptions import ValidationError
        from assets.models import AssetValuation

        client = Client()
        client.force_login(self.specialist)
        listing = client.get(reverse("asset_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, reverse("asset_detail", args=[self.asset.pk]))

        detail = client.get(reverse("asset_detail", args=[self.asset.pk]))
        self.assertEqual(detail.status_code, 200)
        response = client.post(reverse("asset_detail", args=[self.asset.pk]), {
            "action": "add_valuation",
            "valuation_date": "2026-11-07",
            "market_value": "1500000000",
            "insured_value": "1400000000",
            "method": AssetValuation.Method.EXPERT,
            "source_reference": "EXPERT-REF-1",
            "note": "ارزیابی دوره‌ای",
        })
        self.assertEqual(response.status_code, 302)
        valuation = AssetValuation.objects.get(asset=self.asset)
        self.assertEqual(valuation.created_by_id, self.specialist.pk)
        self.assertEqual(valuation.status, AssetValuation.Status.PENDING_APPROVAL)
        self.assertIsNone(valuation.approved_by_id)
        from django.contrib.contenttypes.models import ContentType
        from workflow.models import WorkflowCase
        from workflow.services import transition_case

        valuation_case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(valuation, for_concrete_model=False),
            object_id=str(valuation.pk),
        )
        transition_case(case_id=valuation_case.pk, actor=self.head, action_code="approve")
        transition_case(case_id=valuation_case.pk, actor=self.head, action_code="finalize")
        valuation.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(valuation.status, AssetValuation.Status.APPROVED)
        self.assertEqual(valuation.approved_by_id, self.head.pk)
        self.assertEqual(self.asset.insured_value, valuation.insured_value)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.specialist,
                action="asset_valuation_created",
                object_id=str(self.asset.pk),
            ).exists()
        )
        with self.assertRaises(ValidationError):
            valuation.save()
        with self.assertRaises(ValidationError):
            valuation.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            AssetValuation.objects.filter(pk=valuation.pk).update(status=AssetValuation.Status.REJECTED)

    def test_specialist_can_create_draft_policy_period_and_endorsement_with_secure_download(self):
        from auditlog.models import AuditEvent
        from assets.models import AssetPolicyEndorsement, AssetPolicyPeriod
        from django.core.files.uploadedfile import SimpleUploadedFile

        client = Client()
        client.force_login(self.specialist)
        response = client.post(reverse("asset_detail", args=[self.asset.pk]), {
            "action": "add_policy_period",
            "insurer": str(self.insurer.pk),
            "contract": str(self.contract.pk),
            "policy_number": "OPS-POLICY-2",
            "policy_start": "2026-11-01",
            "policy_end": "2027-10-31",
            "source_reference": "INSURER-POLICY-2",
            "note": "دوره جدید؛ منتظر تأیید",
        })
        self.assertEqual(response.status_code, 302)
        period = AssetPolicyPeriod.objects.get(asset=self.asset, policy_number="OPS-POLICY-2")
        self.assertEqual(period.status, AssetPolicyPeriod.Status.PENDING_APPROVAL)
        self.assertIsNone(period.approved_by_id)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            AssetPolicyPeriod.objects.filter(pk=period.pk).update(status=AssetPolicyPeriod.Status.ACTIVE)
        from django.contrib.contenttypes.models import ContentType
        from workflow.models import WorkflowCase
        from workflow.services import transition_case

        period_case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(period, for_concrete_model=False),
            object_id=str(period.pk),
        )
        transition_case(case_id=period_case.pk, actor=self.head, action_code="approve")
        transition_case(case_id=period_case.pk, actor=self.head, action_code="finalize")
        period.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.ACTIVE)
        self.assertEqual(period.approved_by_id, self.head.pk)
        self.assertEqual(self.asset.policy_number, period.policy_number)

        response = client.post(
            reverse("asset_detail", args=[self.asset.pk]),
            {
                "action": "add_endorsement",
                "policy_period": str(period.pk),
                "endorsement_number": "ENDORSEMENT-1",
                "effective_date": "2026-11-15",
                "description": "اصلاح مشخصات بیمه‌نامه",
                "document": SimpleUploadedFile(
                    "endorsement.pdf",
                    b"%PDF-1.4\nendorsement content",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        endorsement = AssetPolicyEndorsement.objects.get(
            policy_period=period,
            endorsement_number="ENDORSEMENT-1",
        )
        self.assertEqual(endorsement.created_by_id, self.specialist.pk)
        self.assertEqual(endorsement.status, AssetPolicyEndorsement.Status.PENDING_APPROVAL)
        self.assertIsNone(endorsement.approved_by_id)
        with self.assertRaises(ValidationError):
            endorsement.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            AssetPolicyEndorsement.objects.filter(pk=endorsement.pk).update(
                status=AssetPolicyEndorsement.Status.APPROVED
            )
        endorsement_case = WorkflowCase.objects.get(
            content_type=ContentType.objects.get_for_model(endorsement, for_concrete_model=False),
            object_id=str(endorsement.pk),
        )
        transition_case(case_id=endorsement_case.pk, actor=self.head, action_code="approve")
        transition_case(case_id=endorsement_case.pk, actor=self.head, action_code="finalize")
        endorsement.refresh_from_db()
        self.assertEqual(endorsement.status, AssetPolicyEndorsement.Status.APPROVED)
        self.assertEqual(endorsement.approved_by_id, self.head.pk)

        downloaded = client.get(reverse("asset_endorsement_download", args=[endorsement.pk]))
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(b"".join(downloaded.streaming_content), b"%PDF-1.4\nendorsement content")
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.specialist,
                action="asset_policy_endorsement_downloaded",
                object_id=str(self.asset.pk),
            ).exists()
        )

    def test_specialist_can_update_asset_and_vehicle_details_through_scoped_route(self):
        client = Client()
        client.force_login(self.specialist)
        response = client.post(reverse("asset_update", args=[self.asset.pk]), {
            "asset_code": self.asset.asset_code,
            "name": "خودروی عملیاتی ویرایش‌شده",
            "asset_type": InsuredAsset.Type.VEHICLE,
            "company": str(self.company.pk),
            "person": "",
            "identifier": "FLEET-01",
            "location": "سایت مرکزی",
            "insured_value": "1750000000",
            "insurer": str(self.insurer.pk),
            "contract": str(self.contract.pk),
            "policy_number": "BASE-POLICY-1",
            "policy_start": "2026-01-01",
            "policy_end": "2027-01-01",
            "is_active": "on",
            "notes": "به‌روزرسانی اطلاعات دارایی",
            "plate_number": "12الف345",
            "vin": "VIN-AS-OPS-UPDATED",
            "engine_number": "ENG-UPDATED",
            "make": "سازنده",
            "model_name": "مدل جدید",
            "model_year": "2025",
        })
        self.assertEqual(response.status_code, 302, response.context["form"].errors.as_json() if response.context else response.content[:1500])
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.name, "خودروی عملیاتی ویرایش‌شده")
        self.assertEqual(self.asset.insured_value, 1750000000)
        self.asset.vehicle_details.refresh_from_db()
        self.assertEqual(self.asset.vehicle_details.vin, "VIN-AS-OPS-UPDATED")
        self.assertEqual(self.asset.vehicle_details.model_year, 2025)

    def test_company_representative_cannot_create_asset_lifecycle_records(self):
        from accounts.models import RoleAssignment

        representative = User.objects.create_user(
            username="asset-ops-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="third_party",
            reason="نماینده شرکت برای آزمون محدودیت",
        )
        client = Client()
        client.force_login(representative)
        response = client.get(reverse("asset_detail", args=[self.asset.pk]))
        self.assertEqual(response.status_code, 200)
        denied = client.post(reverse("asset_detail", args=[self.asset.pk]), {
            "action": "add_valuation",
            "valuation_date": "2026-11-07",
            "market_value": "100",
            "insured_value": "100",
            "method": "expert",
            "note": "تلاش غیرمجاز",
        })
        self.assertEqual(denied.status_code, 403)

    def test_user_from_another_company_cannot_download_asset_endorsement(self):
        from datetime import date
        from accounts.models import RoleAssignment
        from assets.models import AssetPolicyEndorsement, AssetPolicyPeriod
        from django.core.files.uploadedfile import SimpleUploadedFile

        period = AssetPolicyPeriod.objects.create(
            asset=self.asset,
            insurer=self.insurer,
            contract=self.contract,
            policy_number="AS-PRIVATE-POLICY",
            policy_start=date(2026, 1, 1),
            policy_end=date(2027, 1, 1),
            status=AssetPolicyPeriod.Status.DRAFT,
            created_by=self.specialist,
        )
        endorsement = AssetPolicyEndorsement.objects.create(
            policy_period=period,
            endorsement_number="AS-PRIVATE-ENDORSEMENT",
            description="پیوست محرمانه شرکت",
            document=SimpleUploadedFile(
                "private-endorsement.pdf",
                b"%PDF-1.4\nprivate",
                content_type="application/pdf",
            ),
            created_by=self.specialist,
        )
        other_company = Company.objects.create(code="AS-OTHER", name="شرکت دیگر")
        outsider = User.objects.create_user(
            username="asset-ops-outsider",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=outsider,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=other_company,
            line_code="third_party",
            reason="نماینده شرکت دیگر",
        )
        client = Client()
        client.force_login(outsider)
        response = client.get(reverse("asset_endorsement_download", args=[endorsement.pk]))
        self.assertEqual(response.status_code, 404)



    def test_future_approved_policy_period_activates_only_when_effective_date_arrives(self):
        from datetime import timedelta
        from django.utils import timezone
        from assets.models import AssetPolicyPeriod

        today = timezone.localdate()
        effective_date = today + timedelta(days=2)
        period = AssetPolicyPeriod.objects.create(
            asset=self.asset,
            insurer=self.insurer,
            contract=self.contract,
            policy_number="FUTURE-APPROVED-POLICY",
            policy_start=effective_date,
            policy_end=effective_date + timedelta(days=180),
            status=AssetPolicyPeriod.Status.APPROVED,
            created_by=self.specialist,
            approved_by=self.head,
        )

        self.assertFalse(period.activate_if_due(on_date=today))
        period.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.APPROVED)

        self.assertTrue(period.activate_if_due(on_date=effective_date))
        period.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.ACTIVE)
        self.assertEqual(self.asset.policy_number, period.policy_number)
