from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from organizations.models import Company


class InitialPasswordChangeTests(TestCase):
    def test_user_with_initial_password_flag_is_redirected_to_password_change(self):
        company = Company.objects.create(code="PWD-A", name="شرکت الف")
        user = User.objects.create_user(
            username="pwd-user", password="StrongPass!2026", role="employee", company=company,
            must_change_password=True,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("password_change"))

    def test_user_can_open_password_change_form_while_flag_is_set(self):
        company = Company.objects.create(code="PWD-B", name="شرکت ب")
        user = User.objects.create_user(
            username="pwd-user-2", password="StrongPass!2026", role="employee", company=company,
            must_change_password=True,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)


class AdminAccessIsolationTests(TestCase):
    def test_staff_employee_cannot_open_django_admin(self):
        company = Company.objects.create(code="ADM-A", name="شرکت الف")
        user = User.objects.create_user(
            username="employee-staff", password="StrongPass!2026",
            role="employee", company=company, is_staff=True,
            must_change_password=False,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 403)

    def test_system_admin_can_open_django_admin(self):
        user = User.objects.create_user(
            username="system-admin", password="StrongPass!2026",
            role="system_admin", is_staff=True, must_change_password=False,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
