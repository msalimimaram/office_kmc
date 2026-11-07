from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company
from documents.models import DocumentRecord
from documents.services import add_document_version, create_document


class DocumentUploadAuthorizationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="DOC-A", name="شرکت اسناد")
        self.specialist = User.objects.create_user(
            username="document-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس درمان برای آزمون اسناد",
        )

    def test_specialist_cannot_attach_general_document_to_arbitrary_company(self):
        client = Client()
        client.force_login(self.specialist)
        response = client.post(
            reverse("document_upload"),
            {
                "title": "سند آزمایشی",
                "category": "عمومی",
                "company": str(self.company.pk),
                "security_level": "normal",
                "file": SimpleUploadedFile("test.pdf", b"%PDF-1.7\ncontent"),
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_specialist_cannot_upload_medical_document_by_forging_post(self):
        client = Client()
        client.force_login(self.specialist)
        response = client.post(
            reverse("document_upload"),
            {
                "title": "مدرک پزشکی آزمایشی",
                "category": "پزشکی",
                "security_level": "very_confidential",
                "is_medical": "on",
                "file": SimpleUploadedFile("medical.pdf", b"%PDF-1.7\ncontent"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DocumentRecord.objects.filter(title="مدرک پزشکی آزمایشی").exists())

    def test_medical_document_download_is_limited_to_global_roles(self):
        admin = User.objects.create_user(
            username="document-admin",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه برای آزمون اسناد",
        )
        document = create_document(
            title="مدرک پزشکی محرمانه",
            category="medical",
            upload=SimpleUploadedFile("medical-private.pdf", b"%PDF-1.7\\nprivate"),
            uploaded_by=admin,
            company=self.company,
            is_medical=True,
        )
        client = Client()
        client.force_login(self.specialist)
        response = client.get(reverse("document_download", args=[document.pk]))
        self.assertEqual(response.status_code, 404)

        client.force_login(admin)
        response = client.get(reverse("document_download", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_document_records_and_versions_are_append_only(self):
        document = create_document(
            title="سند نسخه‌دار",
            category="general",
            upload=SimpleUploadedFile("version-1.pdf", b"%PDF-1.7\\nversion1"),
            uploaded_by=self.specialist,
        )
        first_version = document.current_version
        with self.assertRaises(ValidationError):
            DocumentRecord.objects.filter(pk=document.pk).update(title="تغییر مستقیم")
        with self.assertRaises(ValidationError):
            DocumentRecord.objects.filter(pk=document.pk).delete()
        with self.assertRaises(ValidationError):
            document.versions.filter(pk=first_version.pk).update(change_reason="تغییر مستقیم")
        with self.assertRaises(ValidationError):
            document.versions.filter(pk=first_version.pk).delete()

        second_version = add_document_version(
            document_id=document.pk,
            upload=SimpleUploadedFile("version-2.pdf", b"%PDF-1.7\\nversion2"),
            uploaded_by=self.specialist,
            change_reason="اصلاح نسخه آزمایشی",
        )
        first_version.refresh_from_db()
        self.assertFalse(first_version.is_current)
        self.assertTrue(second_version.is_current)
        self.assertEqual(document.versions.count(), 2)



class DocumentManagementFlowTests(TestCase):
    def setUp(self):
        from accounts.models import RoleAssignment
        from documents.services import create_document

        self.admin = User.objects.create_user(
            username="document-lifecycle-admin",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه برای آزمون چرخه سند",
        )
        self.specialist = User.objects.create_user(
            username="document-lifecycle-specialist",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس برای آزمون نسخه سند",
        )
        self.document = create_document(
            title="سند دارای چرخه مدیریت",
            category="general",
            upload=SimpleUploadedFile(
                "document-v1.pdf",
                b"%PDF-1.7\nfirst version",
                content_type="application/pdf",
            ),
            uploaded_by=self.admin,
        )

    def test_specialist_can_add_document_version_and_current_version_is_updated(self):
        from auditlog.models import AuditEvent
        from documents.models import DocumentVersion

        client = Client()
        client.force_login(self.specialist)
        detail = client.get(reverse("document_manage", args=[self.document.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "ثبت نسخه جدید")

        response = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {
                "action": "add_version",
                "change_reason": "اصلاح پیوست قرارداد",
                "file": SimpleUploadedFile(
                    "document-v2.pdf",
                    b"%PDF-1.7\nsecond version",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        versions = list(self.document.versions.order_by("version_number"))
        self.assertEqual(len(versions), 2)
        self.assertFalse(versions[0].is_current)
        self.assertTrue(versions[1].is_current)
        self.assertEqual(self.document.current_version.version_number, 2)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.specialist,
                action="document_version_created",
                object_id=str(self.document.pk),
            ).exists()
        )

    def test_specialist_cannot_archive_or_void_document(self):
        client = Client()
        client.force_login(self.specialist)
        archive = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {"action": "archive", "reason": "آرشیو"},
        )
        self.assertEqual(archive.status_code, 403)
        void = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {"action": "void", "reason": "ابطال"},
        )
        self.assertEqual(void.status_code, 403)
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_archived)
        self.assertFalse(self.document.is_void)

    def test_global_user_can_archive_document_and_archived_download_is_rejected(self):
        from auditlog.models import AuditEvent

        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {"action": "archive", "reason": "نسخه جدید جایگزین شده است."},
        )
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_archived)
        self.assertEqual(self.document.archive_reason, "نسخه جدید جایگزین شده است.")
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="document_archived",
                object_id=str(self.document.pk),
            ).exists()
        )
        denied_download = client.get(reverse("document_download", args=[self.document.pk]))
        self.assertEqual(denied_download.status_code, 404)

    def test_global_user_can_void_document_with_reason_and_audit_event(self):
        from auditlog.models import AuditEvent

        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {"action": "void", "reason": "فایل از مرجع صادرکننده باطل اعلام شد."},
        )
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_void)
        self.assertEqual(self.document.void_reason, "فایل از مرجع صادرکننده باطل اعلام شد.")
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.admin,
                action="document_voided",
                object_id=str(self.document.pk),
            ).exists()
        )

    def test_document_outside_visibility_scope_cannot_be_managed(self):
        outsider = User.objects.create_user(
            username="document-lifecycle-outsider",
            password="StrongPass!2026",
            must_change_password=False,
            role="employee",
        )
        client = Client()
        client.force_login(outsider)
        response = client.get(reverse("document_manage", args=[self.document.pk]))
        self.assertEqual(response.status_code, 404)

    def test_missing_lifecycle_reason_does_not_change_document(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse("document_manage", args=[self.document.pk]),
            {"action": "archive", "reason": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_archived)
