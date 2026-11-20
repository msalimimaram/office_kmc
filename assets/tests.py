from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

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

    def test_company_representative_sees_only_asset_types_in_assigned_lines(self):
        from assets.views import _asset_scope

        other_asset = InsuredAsset.objects.create(
            asset_code="ASSET-A-OTHER",
            name="سایر دارایی خارج از رشته",
            asset_type=InsuredAsset.Type.OTHER,
            company=self.company_a,
            created_by=self.rep,
        )
        fire_rep = User.objects.create_user(
            username="asset-fire-rep",
            password="StrongPass!2026",
            must_change_password=False, company=self.company_a,
        )
        RoleAssignment.objects.create(
            user=fire_rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            line_code="fire",
            reason="نماینده رشته آتش‌سوزی",
        )
        fire_asset = InsuredAsset.objects.create(
            asset_code="ASSET-A-FIRE",
            name="ساختمان تحت پوشش آتش‌سوزی",
            asset_type=InsuredAsset.Type.PROPERTY,
            company=self.company_a,
            created_by=self.rep,
        )
        scoped = _asset_scope(fire_rep)
        self.assertFalse(scoped.filter(pk=other_asset.pk).exists())
        self.assertTrue(scoped.filter(pk=fire_asset.pk).exists())

    def test_company_representative_can_see_dependent_personal_asset_of_active_employee(self):
        from datetime import timedelta
        from django.utils import timezone
        from organizations.models import Person, PersonEmployment

        primary = Person.objects.create(
            company=self.company_a,
            national_id="1234567801",
            first_name="کارمند",
            last_name="اصلی",
            birth_date=timezone.localdate() - timedelta(days=12000),
        )
        PersonEmployment.objects.create(
            person=primary,
            company=self.company_a,
            valid_from=timezone.localdate() - timedelta(days=30),
            status=PersonEmployment.Status.ACTIVE,
        )
        dependent = Person.objects.create(
            company=self.company_a,
            national_id="1234567802",
            first_name="فرد",
            last_name="تحت تکفل",
            birth_date=timezone.localdate() - timedelta(days=8000),
            relationship=Person.Relationship.SPOUSE,
            employee=primary,
        )
        dependent_asset = InsuredAsset.objects.create(
            asset_code="ASSET-A-DEPENDENT",
            name="دارایی شخصی فرد تحت تکفل",
            asset_type=InsuredAsset.Type.PROPERTY,
            person=dependent,
            created_by=self.rep,
        )
        from assets.views import _asset_scope
        self.assertTrue(_asset_scope(self.rep).filter(pk=dependent_asset.pk).exists())

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
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            valid_from=timezone.localdate(),
            reason="مدیر سامانه برای آزمون گردش دارایی",
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
            # The policy period must remain inside the linked contract term.
            "policy_end": "2026-12-31",
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

    def test_specialist_can_update_asset_master_without_changing_policy_or_valuation_snapshot(self):
        from django.core.exceptions import ValidationError
        from assets.forms import InsuredAssetForm

        form = InsuredAssetForm(user=self.specialist, instance=self.asset)
        protected = {
            "insured_value", "insurer", "contract", "policy_number",
            "policy_start", "policy_end",
        }
        self.assertFalse(protected.intersection(form.fields))
        original = {
            "insured_value": self.asset.insured_value,
            "insurer_id": self.asset.insurer_id,
            "contract_id": self.asset.contract_id,
            "policy_number": self.asset.policy_number,
            "policy_start": self.asset.policy_start,
            "policy_end": self.asset.policy_end,
        }

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
            "insurer": "",
            "contract": "",
            "policy_number": "ATTACK-POLICY",
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
        self.assertEqual(response.status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.name, "خودروی عملیاتی ویرایش‌شده")
        for field, expected in original.items():
            self.assertEqual(getattr(self.asset, field), expected)
        self.asset.vehicle_details.refresh_from_db()
        self.assertEqual(self.asset.vehicle_details.vin, "VIN-AS-OPS-UPDATED")
        self.assertEqual(self.asset.vehicle_details.model_year, 2025)

        self.asset.insured_value = 1750000000
        with self.assertRaises(ValidationError):
            self.asset.save()

    def test_existing_policy_snapshot_cannot_be_changed_outside_approval(self):
        from django.core.exceptions import ValidationError

        self.asset.policy_number = "UNAPPROVED-POLICY"
        with self.assertRaises(ValidationError):
            self.asset.save()

    def test_policy_snapshot_queryset_updates_are_rejected(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            InsuredAsset.objects.filter(pk=self.asset.pk).update(
                policy_number="QUERYSET-BYPASS"
            )
        self.asset.refresh_from_db()
        self.assertNotEqual(self.asset.policy_number, "QUERYSET-BYPASS")

    def test_company_representative_cannot_create_asset_lifecycle_records(self):
        from accounts.models import RoleAssignment

        representative = User.objects.create_user(
            username="asset-ops-rep",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
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
            must_change_password=False, company=other_company,
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
            # Keep the test policy within the fixture contract's end date.
            policy_end=effective_date + timedelta(days=30),
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


    def test_valuation_snapshot_is_applied_only_after_final_workflow_close(self):
        from assets.models import AssetValuation
        from workflow.services import start_workflow, transition_case

        original_value = self.asset.insured_value
        valuation = AssetValuation.objects.create(
            asset=self.asset,
            market_value=950000,
            insured_value=875000,
            created_by=self.specialist,
        )
        case = start_workflow(
            obj=valuation,
            code="asset_valuation_approval",
            actor=self.specialist,
            assignee=self.head,
        )
        transition_case(case_id=case.pk, actor=self.head, action_code="approve")

        valuation.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(valuation.status, AssetValuation.Status.PENDING_APPROVAL)
        self.assertEqual(self.asset.insured_value, original_value)

        transition_case(case_id=case.pk, actor=self.head, action_code="finalize")
        valuation.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(valuation.status, AssetValuation.Status.APPROVED)
        self.assertEqual(valuation.approved_by_id, self.head.pk)
        self.assertEqual(self.asset.insured_value, valuation.insured_value)

    def test_policy_period_and_endorsement_commit_only_after_final_workflow_close(self):
        from datetime import timedelta
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from assets.models import AssetPolicyPeriod, AssetPolicyEndorsement
        from workflow.services import start_workflow, transition_case

        today = timezone.localdate()
        period = AssetPolicyPeriod.objects.create(
            asset=self.asset,
            insurer=self.insurer,
            contract=self.contract,
            policy_number="APPROVAL-GATED-POLICY",
            policy_start=today,
            policy_end=today + timedelta(days=30),
            created_by=self.specialist,
        )
        policy_case = start_workflow(
            obj=period,
            code="asset_policy_approval",
            actor=self.specialist,
            assignee=self.head,
        )
        transition_case(case_id=policy_case.pk, actor=self.head, action_code="approve")
        period.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.PENDING_APPROVAL)
        self.assertEqual(self.asset.policy_number, "BASE-POLICY-1")

        transition_case(case_id=policy_case.pk, actor=self.head, action_code="finalize")
        period.refresh_from_db()
        self.asset.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.ACTIVE)
        self.assertEqual(self.asset.policy_number, period.policy_number)

        endorsement = AssetPolicyEndorsement.objects.create(
            policy_period=period,
            endorsement_number="APPROVAL-GATED-ENDORSEMENT",
            effective_date=today,
            description="الحاقیه آزمایشی برای کنترل زمان اعمال",
            document=SimpleUploadedFile(
                "approval-gated-endorsement.pdf",
                b"%PDF-1.4\\nApproval-gated endorsement\\n%%EOF",
                content_type="application/pdf",
            ),
            created_by=self.specialist,
        )
        endorsement_case = start_workflow(
            obj=endorsement,
            code="asset_endorsement_approval",
            actor=self.specialist,
            assignee=self.head,
        )
        transition_case(
            case_id=endorsement_case.pk,
            actor=self.head,
            action_code="approve",
        )
        endorsement.refresh_from_db()
        self.assertEqual(
            endorsement.status, AssetPolicyEndorsement.Status.PENDING_APPROVAL
        )
        transition_case(
            case_id=endorsement_case.pk,
            actor=self.head,
            action_code="finalize",
        )
        endorsement.refresh_from_db()
        self.assertEqual(
            endorsement.status, AssetPolicyEndorsement.Status.APPROVED
        )
        self.assertEqual(endorsement.approved_by_id, self.head.pk)


@override_settings(DEBUG=True, CLAMD_HOST="")
class AssetPolicyLifecycleTests(TestCase):
    def setUp(self):
        from datetime import timedelta
        from django.utils import timezone
        from insurance.models import Contract, Insurer, InsuranceLine

        self.today = timezone.localdate()
        self.company = Company.objects.create(code="AS-LIFECYCLE", name="شرکت چرخه بیمه‌نامه")
        self.insurer = Insurer.objects.create(name="بیمه‌گر چرخه بیمه‌نامه")
        self.user = User.objects.create_user(
            username="asset-lifecycle-user",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.old_contract = Contract.objects.create(
            code="AS-LIFE-OLD",
            title="قرارداد قبلی",
            insurer=self.insurer,
            line=InsuranceLine.FIRE,
            start_date=self.today - timedelta(days=365),
            end_date=self.today - timedelta(days=1),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.new_contract = Contract.objects.create(
            code="AS-LIFE-NEW",
            title="قرارداد جایگزین",
            insurer=self.insurer,
            line=InsuranceLine.FIRE,
            start_date=self.today,
            end_date=self.today + timedelta(days=365),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )
        self.old_contract.companies.add(self.company)
        self.new_contract.companies.add(self.company)

    def test_daily_command_expires_old_policy_and_activates_due_replacement(self):
        from datetime import timedelta
        from assets.models import AssetPolicyPeriod
        from django.core.management import call_command

        asset = InsuredAsset.objects.create(
            asset_code="AS-LIFE-ASSET",
            name="ساختمان اداری",
            asset_type=InsuredAsset.Type.PROPERTY,
            company=self.company,
            insurer=self.insurer,
            contract=self.old_contract,
            policy_number="OLD-POLICY",
            policy_start=self.today - timedelta(days=365),
            policy_end=self.today - timedelta(days=1),
            created_by=self.user,
        )
        old_period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=self.insurer,
            contract=self.old_contract,
            policy_number="OLD-POLICY",
            policy_start=self.today - timedelta(days=365),
            policy_end=self.today - timedelta(days=1),
            status=AssetPolicyPeriod.Status.ACTIVE,
            created_by=self.user,
        )
        new_period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=self.insurer,
            contract=self.new_contract,
            policy_number="NEW-POLICY",
            policy_start=self.today,
            policy_end=self.today + timedelta(days=365),
            status=AssetPolicyPeriod.Status.APPROVED,
            created_by=self.user,
        )

        call_command("apply_due_asset_policy_periods")

        old_period.refresh_from_db()
        new_period.refresh_from_db()
        asset.refresh_from_db()
        self.assertEqual(old_period.status, AssetPolicyPeriod.Status.EXPIRED)
        self.assertEqual(new_period.status, AssetPolicyPeriod.Status.ACTIVE)
        self.assertEqual(asset.contract_id, self.new_contract.pk)
        self.assertEqual(asset.policy_number, "NEW-POLICY")

    def test_approved_period_does_not_activate_after_contract_expiration(self):
        from datetime import timedelta
        from assets.models import AssetPolicyPeriod
        from insurance.models import Contract

        asset = InsuredAsset.objects.create(
            asset_code="AS-LIFE-CONTRACT-EXPIRED",
            name="دارایی قرارداد منقضی",
            asset_type=InsuredAsset.Type.PROPERTY,
            company=self.company,
            created_by=self.user,
        )
        period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=self.insurer,
            contract=self.new_contract,
            policy_number="CONTRACT-EXPIRED-POLICY",
            policy_start=self.today,
            policy_end=self.today + timedelta(days=90),
            status=AssetPolicyPeriod.Status.APPROVED,
            created_by=self.user,
        )
        self.new_contract.status = Contract.Status.EXPIRED
        self.new_contract.save()
        self.assertTrue(period.activate_if_due(on_date=self.today))
        period.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.EXPIRED)

    def test_active_period_is_terminated_when_its_contract_is_terminated(self):
        from datetime import timedelta
        from assets.models import AssetPolicyPeriod
        from insurance.models import Contract

        asset = InsuredAsset.objects.create(
            asset_code="AS-LIFE-CONTRACT-TERMINATED",
            name="دارایی قرارداد فسخ‌شده",
            asset_type=InsuredAsset.Type.PROPERTY,
            company=self.company,
            created_by=self.user,
        )
        period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=self.insurer,
            contract=self.new_contract,
            policy_number="CONTRACT-TERMINATED-POLICY",
            policy_start=self.today,
            policy_end=self.today + timedelta(days=90),
            status=AssetPolicyPeriod.Status.ACTIVE,
            created_by=self.user,
        )
        self.new_contract.status = Contract.Status.TERMINATED
        self.new_contract.save()
        self.assertTrue(period.expire_if_due(on_date=self.today))
        period.refresh_from_db()
        self.assertEqual(period.status, AssetPolicyPeriod.Status.TERMINATED)

    def test_person_asset_contract_scope_uses_current_employment_not_legacy_company(self):
        from datetime import timedelta
        from organizations.models import Person, PersonEmployment
        from assets.models import AssetPolicyPeriod

        former_company = Company.objects.create(code="AS-LIFE-FORMER", name="شرکت قبلی مالک")
        person = Person.objects.create(
            company=former_company,
            national_id="1234567890",
            first_name="مالک",
            last_name="آزمایشی",
            birth_date=self.today - timedelta(days=12000),
        )
        PersonEmployment.objects.create(
            person=person,
            company=self.company,
            personnel_code="NEW-EMP-01",
            valid_from=self.today - timedelta(days=30),
            status=PersonEmployment.Status.ACTIVE,
        )
        asset = InsuredAsset.objects.create(
            asset_code="AS-LIFE-PERSON",
            name="دارایی شخصی کارمند",
            asset_type=InsuredAsset.Type.PROPERTY,
            person=person,
            created_by=self.user,
        )
        period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=self.insurer,
            contract=self.new_contract,
            policy_number="PERSON-POLICY",
            policy_start=self.today,
            policy_end=self.today + timedelta(days=365),
            status=AssetPolicyPeriod.Status.PENDING_APPROVAL,
            created_by=self.user,
        )
        self.assertEqual(period.contract_id, self.new_contract.pk)
