from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company


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
        self.assertEqual(response.context["messages"].__len__(), 1)
        self.assertFalse(
            __import__("documents.models", fromlist=["DocumentRecord"]).DocumentRecord.objects.filter(
                title="مدرک پزشکی آزمایشی"
            ).exists()
        )
