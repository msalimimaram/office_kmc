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
    def test_seed_is_idempotent_and_never_resets_existing_user_password(self):
        from django.core.management import call_command
        from accounts.models import User
        from claims.models import Claim, ClaimPayment
        from organizations.models import Company, Person
        from requests_portal.models import ServiceRequest

        call_command("seed_demo")
        employee = User.objects.get(username="employee.a")
        employee.set_password("LocallyChosen!Password2026")
        employee.save(update_fields=["password"])

        model_counts = {
            model: model.objects.count()
            for model in (Company, Person, User, Claim, ClaimPayment, ServiceRequest)
        }

        call_command("seed_demo")

        employee.refresh_from_db()
        self.assertTrue(employee.check_password("LocallyChosen!Password2026"))
        for model, count in model_counts.items():
            self.assertEqual(model.objects.count(), count, model._meta.label)
        self.assertFalse(User.objects.get(username="head.demo").has_usable_password())

    def test_seed_collision_aborts_without_overwriting_or_partial_creation(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from organizations.models import Company

        company = Company.objects.create(
            code="DEMO-A",
            name="رکورد موجود نباید تغییر کند",
            is_parent=False,
            is_active=True,
        )

        with self.assertRaises(CommandError):
            call_command("seed_demo")

        company.refresh_from_db()
        self.assertEqual(company.name, "رکورد موجود نباید تغییر کند")
        self.assertFalse(Company.objects.filter(code="DEMO-B").exists())


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
