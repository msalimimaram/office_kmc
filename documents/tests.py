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
        with self.assertRaises(Exception):
            DocumentRecord.objects.filter(pk=document.pk).update(title="تغییر مستقیم")
        with self.assertRaises(Exception):
            DocumentRecord.objects.filter(pk=document.pk).delete()
        with self.assertRaises(Exception):
            document.versions.filter(pk=first_version.pk).update(change_reason="تغییر مستقیم")
        with self.assertRaises(Exception):
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
