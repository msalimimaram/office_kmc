from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from organizations.models import Company
from requests_portal.models import ServiceRequest

class ServiceRequestTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="A", name="شرکت الف")
        self.user = User.objects.create_user(username="emp", password="StrongPass!2026", role="employee", company=self.company)
    def test_user_can_submit_request(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {"kind":"other", "title":"درخواست آزمایشی", "description":"شرح آزمایشی"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.first().submitted_by, self.user)
