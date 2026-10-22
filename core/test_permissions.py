from django.test import TestCase

from accounts.models import User
from core.permissions import scoped_requests_for
from organizations.models import Company
from requests_portal.models import ServiceRequest


class ConfidentialRequestScopeTests(TestCase):
    def test_specialist_cannot_see_confidential_request_even_if_assigned(self):
        company = Company.objects.create(code="SCOPE-A", name="شرکت آزمایشی")
        employee = User.objects.create_user(
            username="scope-employee", password="StrongPass!2026",
            role="employee", company=company, must_change_password=False,
        )
        specialist = User.objects.create_user(
            username="scope-specialist", password="StrongPass!2026",
            role="insurance_specialist", must_change_password=False,
        )
        item = ServiceRequest.objects.create(
            reference="IB-LEGACY-SECRET", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=employee, company=company, assigned_to=specialist,
            title="محرمانه", description="شرح محرمانه", is_confidential=True,
        )
        self.assertNotIn(item, scoped_requests_for(specialist))
