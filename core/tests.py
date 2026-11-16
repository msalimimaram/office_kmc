from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
import struct
from zipfile import ZIP_DEFLATED, ZipFile
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from core.uploads import validate_uploaded_file


@override_settings(DEBUG=True, CLAMD_HOST="")
class UploadedFileValidationTests(SimpleTestCase):
    def test_accepts_pdf_signature(self):
        upload = SimpleUploadedFile("sample.pdf", b"%PDF-1.7\ncontent")
        self.assertIsNone(validate_uploaded_file(upload, max_size=1024))

    def test_rejects_mislabeled_text_file(self):
        upload = SimpleUploadedFile("not-really.pdf", b"this is plain text")
        self.assertIn("مطابقت ندارد", validate_uploaded_file(upload, max_size=1024))

    def test_rejects_oversized_file_before_content_parsing(self):
        upload = SimpleUploadedFile("large.pdf", b"%PDF-1.7\n")
        self.assertIn("حداکثر حجم", validate_uploaded_file(upload, max_size=4))


    def test_rejects_disallowed_extension(self):
        upload = SimpleUploadedFile("payload.exe", b"MZ\x00\x01")
        self.assertIn("نوع فایل مجاز", validate_uploaded_file(upload, max_size=1024))

    def test_upload_stream_is_rewound_after_validation(self):
        upload = SimpleUploadedFile("bad.pdf", b"not a pdf")
        upload.read(3)
        validate_uploaded_file(upload, max_size=1024)
        self.assertEqual(upload.tell(), 0)

    def test_rejects_office_zip_without_expected_document_part(self):
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("random.txt", "not a workbook")
        upload = SimpleUploadedFile("fake.xlsx", stream.getvalue())
        self.assertIn("مطابقت ندارد", validate_uploaded_file(upload, max_size=1024 * 1024))



class FakeClamAVSocket:
    def __init__(self, response, *, chunk_size=None):
        self.remaining = bytearray(response)
        self.chunk_size = chunk_size
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.extend(data)

    def recv(self, size):
        limit = min(size, self.chunk_size or size)
        chunk = bytes(self.remaining[:limit])
        del self.remaining[:limit]
        return chunk


class ClamAVUploadScanningTests(SimpleTestCase):
    @override_settings(DEBUG=False, CLAMD_HOST="clamd.internal", CLAMD_PORT=3310, CLAMD_TIMEOUT=5)
    @patch("core.uploads.socket.create_connection")
    def test_clean_file_is_accepted_only_after_clamav_ok(self, create_connection):
        scanner = FakeClamAVSocket(b"stream: OK\0", chunk_size=3)
        create_connection.return_value = scanner
        upload = SimpleUploadedFile("clean.pdf", b"%PDF-1.7\\nsynthetic content")

        self.assertIsNone(validate_uploaded_file(upload, max_size=1024))

        create_connection.assert_called_once_with(("clamd.internal", 3310), timeout=5.0)
        payload = upload.read()
        upload.seek(0)
        expected_stream = (
            b"zINSTREAM\0"
            + struct.pack("!I", len(payload))
            + payload
            + struct.pack("!I", 0)
        )
        self.assertEqual(bytes(scanner.sent), expected_stream)
        self.assertEqual(upload.tell(), 0)

    @override_settings(DEBUG=False, CLAMD_HOST="clamd.internal", CLAMD_PORT=3310, CLAMD_TIMEOUT=5)
    @patch("core.uploads.socket.create_connection")
    def test_truncated_clean_reply_without_nul_fails_closed(self, create_connection):
        create_connection.return_value = FakeClamAVSocket(b"stream: OK")
        upload = SimpleUploadedFile("truncated.pdf", b"%PDF-1.7\\nsynthetic content")

        error = validate_uploaded_file(upload, max_size=1024)

        self.assertIn("پاسخ اسکنر", error)

    @override_settings(DEBUG=False, CLAMD_HOST="clamd.internal", CLAMD_PORT=3310, CLAMD_TIMEOUT=5)
    @patch("core.uploads.socket.create_connection")
    def test_reply_with_ok_substring_but_invalid_status_fails_closed(self, create_connection):
        create_connection.return_value = FakeClamAVSocket(b"stream: NOT OK\0")
        upload = SimpleUploadedFile("invalid-reply.pdf", b"%PDF-1.7\\nsynthetic content")

        error = validate_uploaded_file(upload, max_size=1024)

        self.assertIn("پاسخ اسکنر", error)

    @override_settings(DEBUG=False, CLAMD_HOST="clamd.internal", CLAMD_PORT=3310, CLAMD_TIMEOUT=5)
    @patch("core.uploads.socket.create_connection")
    def test_infected_file_is_rejected(self, create_connection):
        create_connection.return_value = FakeClamAVSocket(
            b"stream: Eicar-Test-Signature FOUND\0"
        )
        upload = SimpleUploadedFile("infected.pdf", b"%PDF-1.7\\nsynthetic content")

        error = validate_uploaded_file(upload, max_size=1024)

        self.assertIn("آلوده", error)

    @override_settings(DEBUG=False, CLAMD_HOST="")
    def test_production_rejects_upload_when_scanner_is_not_configured(self):
        upload = SimpleUploadedFile("unscanned.pdf", b"%PDF-1.7\\nsynthetic content")

        error = validate_uploaded_file(upload, max_size=1024)

        self.assertIn("پیکربندی نشده", error)

    @override_settings(DEBUG=False, CLAMD_HOST="clamd.internal")
    @patch("core.uploads.socket.create_connection", side_effect=OSError("scanner unavailable"))
    def test_scanner_unavailable_fails_closed(self, create_connection):
        upload = SimpleUploadedFile("offline.pdf", b"%PDF-1.7\\nsynthetic content")

        error = validate_uploaded_file(upload, max_size=1024)

        self.assertIn("برقرار نشد", error)


class WorkflowCoverageCommandTests(TestCase):
    def test_workflow_audit_fails_when_request_kinds_are_not_configured(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError

        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_workflows", stdout=output)
        self.assertIn("identity_change", output.getvalue())


    def test_workflow_audit_rejects_request_steps_without_status_mapping(self):
        from io import StringIO
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from accounts.models import RoleAssignment, User
        from requests_portal.models import ServiceRequest
        from workflow.models import WorkflowDefinition, WorkflowStep

        admin_user = User.objects.create_superuser(
            username="workflow-audit-admin",
            email="workflow-audit@example.invalid",
            password="StrongPass!123",
        )
        RoleAssignment.objects.create(
            user=admin_user,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه برای آزمون ممیزی گردش‌کار",
        )
        for kind, _label in ServiceRequest.Kind.choices:
            definition = WorkflowDefinition.objects.create(
                code=kind,
                title=f"گردش کار {kind}",
                created_by=admin_user,
            )
            WorkflowStep.objects.create(
                definition=definition,
                code="unmapped-step" if kind == ServiceRequest.Kind.OTHER else ServiceRequest.Status.SUBMITTED,
                title="مرحله آغازین",
                order=1,
                allowed_roles=[RoleAssignment.Role.SYSTEM_ADMIN],
                is_initial=True,
                is_terminal=True,
                allow_return=False,
            )
            definition.approved_by = admin_user
            definition.is_active = True
            definition.save()

        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_workflows", stdout=output)
        self.assertIn("unmapped-step", output.getvalue())


class StaticAndPrivateMediaUrlTests(SimpleTestCase):
    def test_static_and_private_media_urls_are_root_relative(self):
        from django.conf import settings
        from django.templatetags.static import static

        self.assertTrue(settings.STATIC_URL.startswith("/"))
        self.assertTrue(settings.MEDIA_URL.startswith("/"))
        self.assertTrue(static("css/site.css").startswith("/static/"))



@override_settings(DEBUG=True)
class DemoSeedCommandSafetyTests(TestCase):
    def test_seed_guard_allows_only_pristine_migration_bootstrap_calendar(self):
        from workflow.models import BusinessCalendar
        from core.management.commands.seed_demo import _assert_empty_disposable_database

        calendar = BusinessCalendar.objects.get(code="iran-default")
        self.assertEqual(calendar.title, "تقویم کاری مجموعه")
        self.assertEqual(calendar.timezone_name, "Asia/Tehran")
        self.assertEqual(calendar.working_weekdays, [5, 6, 0, 1, 2, 3])
        self.assertEqual(calendar.start_time.isoformat(timespec="minutes"), "08:00")
        self.assertEqual(calendar.end_time.isoformat(timespec="minutes"), "16:00")
        self.assertTrue(calendar.is_active)

        # The pristine singleton is created by workflow.0001_initial and is
        # the only existing application row permitted by the seed guard.
        _assert_empty_disposable_database()

    def test_seed_guard_rejects_a_modified_or_additional_business_calendar(self):
        from django.core.management.base import CommandError
        from workflow.models import BusinessCalendar
        from core.management.commands.seed_demo import _assert_empty_disposable_database

        calendar = BusinessCalendar.objects.get(code="iran-default")
        calendar.title = "تقویم تغییر یافته"
        calendar.save(update_fields=["title"])

        with self.assertRaises(CommandError) as raised:
            _assert_empty_disposable_database()

        self.assertIn("workflow.BusinessCalendar", str(raised.exception))
        calendar.refresh_from_db()
        self.assertEqual(calendar.title, "تقویم تغییر یافته")

    def test_seed_guard_rejects_an_additional_business_calendar(self):
        from django.core.management.base import CommandError
        from workflow.models import BusinessCalendar
        from core.management.commands.seed_demo import _assert_empty_disposable_database

        extra = BusinessCalendar.objects.create(
            code="second-business-calendar",
            title="تقویم دوم",
        )

        with self.assertRaises(CommandError) as raised:
            _assert_empty_disposable_database()

        self.assertIn("workflow.BusinessCalendar", str(raised.exception))
        extra.refresh_from_db()
        self.assertEqual(extra.code, "second-business-calendar")

    def test_seed_is_one_shot_and_rerun_fails_without_mutating_existing_data(self):
        from django.apps import apps
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from accounts.models import User

        seed_environment = {"DEMO_SEED_PASSWORD": "unit-test-only-seed-password"}
        with patch.dict("os.environ", seed_environment):
            call_command("seed_demo")

        from datetime import date
        from organizations.models import (
            CompanyLeadershipTitle, Person, PersonEmployment, PersonRelationship,
        )
        historical_titles = CompanyLeadershipTitle.objects.filter(
            title="مدیرعامل",
            valid_from__lt=date(2026, 1, 1),
        ).select_related("person", "company", "declared_by")
        self.assertTrue(historical_titles.exists())
        for appointment in historical_titles:
            employment = PersonEmployment.objects.get(
                person=appointment.person,
                company=appointment.company,
                source_reference__startswith="DEMO-PRES-HISTORY-",
            )
            self.assertEqual(appointment.valid_from, employment.valid_from)
            self.assertEqual(appointment.valid_until, employment.valid_until)
            self.assertEqual(appointment.declared_by.company_id, appointment.company_id)

        dependent_c = Person.objects.get(national_id="0012345685")
        dependent_d = Person.objects.get(national_id="0012345686")
        primary_c = Person.objects.get(national_id="0012345682")
        primary_d = Person.objects.get(national_id="0012345683")
        self.assertEqual(dependent_c.employee_id, primary_c.pk)
        self.assertEqual(dependent_d.employee_id, primary_d.pk)
        self.assertTrue(PersonRelationship.objects.filter(
            dependent_person=dependent_c,
            primary_person=primary_c,
            relationship_type=Person.Relationship.SPOUSE,
            status=PersonRelationship.Status.ACTIVE,
        ).exists())
        self.assertTrue(PersonRelationship.objects.filter(
            dependent_person=dependent_d,
            primary_person=primary_d,
            relationship_type=Person.Relationship.CHILD,
            status=PersonRelationship.Status.ACTIVE,
        ).exists())

        employee = User.objects.get(username="employee.a")
        employee.set_password("LocallyChosen!Password2026")
        employee.save(update_fields=["password"])

        managed_models = [
            model for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy and not model._meta.swapped
        ]
        model_counts = {model: model.objects.count() for model in managed_models}

        with patch.dict("os.environ", seed_environment):
            with self.assertRaises(CommandError) as raised:
                call_command("seed_demo")

        self.assertIn("empty, disposable database", str(raised.exception))
        employee.refresh_from_db()
        self.assertTrue(employee.check_password("LocallyChosen!Password2026"))
        for model, count in model_counts.items():
            self.assertEqual(model.objects.count(), count, model._meta.label)
        self.assertFalse(User.objects.filter(username="head.demo").exists())

    def test_presentation_seed_never_assigns_a_password_to_an_existing_unusable_account(self):
        from django.core.management.base import CommandError
        from accounts.models import User
        from core.management.commands.presentation_expansion import _ensure_user

        existing_user = User.objects.create(
            username="presentation-existing",
            role=User.Role.SYSTEM_ADMIN,
            first_name="مدیر",
            last_name="سامانه",
            is_active=True,
        )
        existing_user.set_unusable_password()
        existing_user.save(update_fields=["password"])
        must_change_before = existing_user.must_change_password

        with patch.dict("os.environ", {"DEMO_SEED_PASSWORD": "unit-test-only-seed-password"}):
            with self.assertRaises(CommandError) as raised:
                _ensure_user(
                    username="presentation-existing",
                    role=User.Role.SYSTEM_ADMIN,
                )

        self.assertIn("no usable password", str(raised.exception))
        existing_user.refresh_from_db()
        self.assertFalse(existing_user.has_usable_password())
        self.assertEqual(existing_user.must_change_password, must_change_before)

    def test_seed_requires_empty_database_and_preserves_existing_company(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from organizations.models import Company

        company = Company.objects.create(
            code="DEMO-A",
            name="رکورد موجود نباید تغییر کند",
            is_parent=False,
            is_active=True,
        )

        with patch.dict("os.environ", {"DEMO_SEED_PASSWORD": "unit-test-only-seed-password"}):
            with self.assertRaises(CommandError) as raised:
                call_command("seed_demo")
        self.assertIn("empty, disposable database", str(raised.exception))

        company.refresh_from_db()
        self.assertEqual(company.name, "رکورد موجود نباید تغییر کند")
        self.assertFalse(Company.objects.filter(code="DEMO-B").exists())


    def test_existing_fixture_without_verification_allowlist_fails_closed(self):
        from django.core.management.base import CommandError
        from core.management.commands.seed_demo import _get_or_create_unchanged
        from organizations.models import Company

        company = Company.objects.create(
            code="SEED-VERIFY-GUARD",
            name="رکورد موجود باید حفظ شود",
            is_parent=False,
            is_active=True,
        )
        with self.assertRaises(CommandError) as raised:
            _get_or_create_unchanged(
                Company,
                lookup={"code": "SEED-VERIFY-GUARD"},
                defaults={"name": "نام جایگزین", "is_parent": True, "is_active": False},
                verify_fields=(),
            )
        self.assertIn("Unsafe seed reuse", str(raised.exception))
        company.refresh_from_db()
        self.assertEqual(company.name, "رکورد موجود باید حفظ شود")
        self.assertFalse(company.is_parent)
        self.assertTrue(company.is_active)

    def test_presentation_seed_reuses_only_an_identical_scoped_role_assignment(self):
        from datetime import date
        from accounts.models import RoleAssignment, User
        from core.management.commands.presentation_expansion import _ensure_role_assignment
        from core.management.commands.seed_demo import _get_or_create_unchanged
        from organizations.models import Company, Person

        company = Company.objects.create(
            code="SEED-ROLE-VERIFY",
            name="شرکت آزمون انتصاب",
        )
        admin = User.objects.create_user(
            username="seed-role-admin",
            password="StrongPass!2026",
            must_change_password=False,
        )
        representative = User.objects.create_user(
            username="seed-role-representative",
            password="StrongPass!2026",
            must_change_password=False,
            company=company,
        )
        Person.objects.create(
            company=company,
            user=representative,
            national_id="1234567890",
            first_name="کاربر",
            last_name="آزمایشی",
            birth_date=date(1990, 1, 1),
            relationship=Person.Relationship.EMPLOYEE,
        )
        existing = RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company,
            insurer=None,
            line_code="*",
            valid_from=date(2026, 1, 1),
            valid_until=None,
            is_active=True,
            reason="دلیل ثبت‌شده در seed پایه",
            granted_by=admin,
            approved_by=admin,
        )

        def record(model, lookup, defaults, verify_fields=None):
            return _get_or_create_unchanged(
                model, lookup=lookup, defaults=defaults, verify_fields=verify_fields
            )

        reused = _ensure_role_assignment(
            record,
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company,
            insurer=None,
            line_code="*",
            granted_by=admin,
            approved_by=admin,
            reason="شرح متفاوت در لایه گسترش نمایشی",
        )

        self.assertEqual(reused.pk, existing.pk)

        support_reused, created = _get_or_create_unchanged(
            RoleAssignment,
            lookup={
                "user": representative,
                "role": RoleAssignment.Role.SUBSIDIARY_REP,
                "company": company,
                "insurer": None,
                "line_code": "*",
            },
            defaults={
                "valid_from": date(2026, 1, 1),
                "valid_until": None,
                "is_active": True,
                "reason": "انتصاب تکمیلی داده نمونه",
                "granted_by": admin,
                "approved_by": admin,
            },
            verify_fields=("valid_from", "valid_until", "is_active", "granted_by", "approved_by"),
        )
        self.assertFalse(created)
        self.assertEqual(support_reused.pk, existing.pk)
        reused.refresh_from_db()
        self.assertEqual(reused.reason, "دلیل ثبت‌شده در seed پایه")
        self.assertEqual(RoleAssignment.objects.filter(user=representative).count(), 1)



class SubsidiaryRepresentativeLineScopeTests(TestCase):
    def setUp(self):
        from datetime import date
        from accounts.models import RoleAssignment, User
        from claims.models import Claim
        from insurance.models import Contract, Insurer, InsuranceLine
        from organizations.models import Company, Person
        from core.permissions import scoped_claims_for

        self.scoped_claims_for = scoped_claims_for
        self.company = Company.objects.create(
            code="LINE-SCOPE-A",
            name="شرکت دارای نمایندگی رشته‌ای",
        )
        self.other_company = Company.objects.create(
            code="LINE-SCOPE-B",
            name="شرکت خارج از محدوده",
        )
        self.insurer = Insurer.objects.create(name="بیمه‌گر ممیزی رشته")
        self.person = Person.objects.create(
            company=self.company,
            national_id="9911223344",
            first_name="بیمه‌شده",
            last_name="آزمون",
            birth_date=date(1990, 1, 1),
        )

        def contract(code, company, line):
            item = Contract.objects.create(
                code=code,
                title=f"قرارداد {code}",
                insurer=self.insurer,
                line=line,
                start_date=date(2026, 1, 1),
                end_date=date(2028, 12, 31),
                is_active=True,
            )
            item.companies.add(company)
            return item

        self.health_contract = contract(
            "LINE-SCOPE-HEALTH", self.company, InsuranceLine.HEALTH
        )
        self.body_contract = contract(
            "LINE-SCOPE-BODY", self.company, InsuranceLine.BODY
        )
        self.other_company_contract = contract(
            "LINE-SCOPE-OTHER", self.other_company, InsuranceLine.HEALTH
        )

        self.health_claim = Claim.objects.create(
            claim_number="LINE-SCOPE-CLAIM-HEALTH",
            person=self.person,
            company_snapshot=self.company,
            contract=self.health_contract,
            insurer=self.insurer,
            service_type="خدمت درمانی",
        )
        self.body_claim = Claim.objects.create(
            claim_number="LINE-SCOPE-CLAIM-BODY",
            person=self.person,
            company_snapshot=self.company,
            contract=self.body_contract,
            insurer=self.insurer,
            service_type="خسارت خودرو",
        )
        self.other_company_claim = Claim.objects.create(
            claim_number="LINE-SCOPE-CLAIM-OTHER",
            person=self.person,
            company_snapshot=self.other_company,
            contract=self.other_company_contract,
            insurer=self.insurer,
            service_type="خدمت درمانی شرکت دیگر",
        )

    def test_line_limited_representative_sees_only_claims_in_their_company_and_line(self):
        from accounts.models import RoleAssignment, User

        representative = User.objects.create_user(
            username="line-health-representative",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="health",
            reason="نماینده محدود به رشته درمان",
        )

        visible = set(self.scoped_claims_for(representative).values_list("pk", flat=True))
        self.assertIn(self.health_claim.pk, visible)
        self.assertNotIn(self.body_claim.pk, visible)
        self.assertNotIn(self.other_company_claim.pk, visible)


    def test_line_limited_representative_sees_only_unambiguously_scoped_request_types(self):
        from accounts.models import RoleAssignment, User
        from requests_portal.models import ServiceRequest
        from core.permissions import scoped_requests_for

        submitter = User.objects.create_user(
            username="line-request-submitter",
            password="StrongPass!2026",
            must_change_password=False,
        )
        representative = User.objects.create_user(
            username="line-request-representative",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="health",
            reason="نماینده درمان شرکت",
        )
        health_request = ServiceRequest.objects.create(
            reference="LINE-REQ-HEALTH",
            kind=ServiceRequest.Kind.ADD_COVERAGE,
            submitted_by=submitter,
            company=self.company,
            title="افزایش پوشش درمان",
            description="درخواست درمان",
        )
        ambiguous_request = ServiceRequest.objects.create(
            reference="LINE-REQ-OTHER",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=submitter,
            company=self.company,
            title="درخواست با رشته نامشخص",
            description="نوع درخواست فاقد رشته صریح است",
        )

        visible = set(
            scoped_requests_for(representative).values_list("pk", flat=True)
        )
        self.assertIn(health_request.pk, visible)
        self.assertNotIn(ambiguous_request.pk, visible)

    def test_explicit_all_line_representative_sees_all_lines_but_not_other_companies(self):
        from accounts.models import RoleAssignment, User

        representative = User.objects.create_user(
            username="line-all-representative",
            password="StrongPass!2026",
            must_change_password=False, company=self.company,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="*",
            reason="نماینده کل شرکت",
        )

        visible = set(self.scoped_claims_for(representative).values_list("pk", flat=True))
        self.assertIn(self.health_claim.pk, visible)
        self.assertIn(self.body_claim.pk, visible)
        self.assertNotIn(self.other_company_claim.pk, visible)

class DatabaseSchemaVerificationTests(TestCase):
    def test_schema_verification_covers_all_managed_models(self):
        from io import StringIO
        from django.core.management import call_command
        from django.apps import apps

        output = StringIO()
        call_command("verify_database_schema", stdout=output)

        expected_tables = {
            model._meta.db_table
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy and not model._meta.swapped
        }
        self.assertGreater(len(expected_tables), 5)
        self.assertIn(f"all {len(expected_tables)} managed model", output.getvalue())
