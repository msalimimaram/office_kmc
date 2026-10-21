from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from organizations.models import Company
from requests_portal.models import ServiceRequest
from core.permissions import scoped_requests_for


class ServiceRequestTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="A", name="شرکت الف")
        self.other_company = Company.objects.create(code="B", name="شرکت ب")
        self.user = User.objects.create_user(
            username="emp", password="StrongPass!2026", role="employee", company=self.company
        )

    def test_user_can_submit_request(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": "other", "title": "درخواست آزمایشی", "description": "شرح آزمایشی"
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.first().submitted_by, self.user)

    def test_subsidiary_representative_cannot_see_confidential_or_other_company_requests(self):
        rep = User.objects.create_user(
            username="rep", password="StrongPass!2026", role="subsidiary_rep", company=self.company
        )
        ServiceRequest.objects.create(
            reference="IB-PUBLIC-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست عادی", description="شرح",
        )
        ServiceRequest.objects.create(
            reference="IB-SECRET-1", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.user, company=self.company,
            title="درخواست محرمانه", description="شرح محرمانه", is_confidential=True,
        )
        ServiceRequest.objects.create(
            reference="IB-OTHER-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.other_company,
            title="شرکت دیگر", description="شرح",
        )
        visible = set(scoped_requests_for(rep).values_list("reference", flat=True))
        self.assertIn("IB-PUBLIC-1", visible)
        self.assertNotIn("IB-SECRET-1", visible)
        self.assertNotIn("IB-OTHER-1", visible)

    def test_employee_sees_only_requests_they_submitted(self):
        ServiceRequest.objects.create(
            reference="IB-OWN-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست خودم", description="شرح",
        )
        ServiceRequest.objects.create(
            reference="IB-OTHER-2", kind=ServiceRequest.Kind.OTHER,
            submitted_by=User.objects.create_user(
                username="other-emp", password="StrongPass!2026", role="employee", company=self.other_company
            ),
            company=self.other_company, title="درخواست دیگری", description="شرح",
        )
        visible = set(scoped_requests_for(self.user).values_list("reference", flat=True))
        self.assertEqual(visible, {"IB-OWN-1"})
