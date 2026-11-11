from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    User, UserNotification, OrganizationalUnit, OrganizationalPosition, PositionAssignment,
)
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


from django.core.cache import cache


class LoginThrottlingTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_repeated_invalid_password_attempts_are_throttled(self):
        client = Client()
        login_url = reverse("login")
        for _ in range(5):
            response = client.post(login_url, {
                "username": "unknown-account",
                "password": "incorrect-password",
            }, REMOTE_ADDR="192.0.2.10")
            self.assertEqual(response.status_code, 200)

        response = client.post(login_url, {
            "username": "unknown-account",
            "password": "incorrect-password",
        }, REMOTE_ADDR="192.0.2.10")
        self.assertEqual(response.status_code, 200)
        self.assertIn("login_throttled", response.context["form"].errors.as_data().get("__all__", [])[0].code)

    def test_throttle_is_scoped_to_username_and_client_ip(self):
        client = Client()
        login_url = reverse("login")
        for _ in range(5):
            client.post(login_url, {
                "username": "unknown-account",
                "password": "incorrect-password",
            }, REMOTE_ADDR="192.0.2.11")

        response = client.post(login_url, {
            "username": "unknown-account",
            "password": "incorrect-password",
        }, REMOTE_ADDR="192.0.2.12")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("login_throttled", [
            error.code for error in response.context["form"].errors.as_data().get("__all__", [])
        ])



class UserNotificationTests(TestCase):
    def setUp(self):
        self.recipient = User.objects.create_user(
            username="notification-recipient",
            password="StrongPass!2026", role="employee",
            must_change_password=False,
        )
        self.other = User.objects.create_user(
            username="notification-other",
            password="StrongPass!2026", role="employee",
            must_change_password=False,
        )
        self.notification = UserNotification.objects.create(
            recipient=self.recipient,
            actor=self.other,
            title="درخواست اصلاح اطلاعات تأیید شد",
            body="درخواست شما با موفقیت بررسی شد.",
            target_url="/organizations/person-changes/42/",
        )

    def test_notification_inbox_is_private_and_exposes_unread_count(self):
        client = Client()
        client.force_login(self.recipient)
        response = client.get(reverse("notification_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.notification.title)
        self.assertEqual(response.context["unread_notification_count"], 1)

        client.force_login(self.other)
        other_response = client.get(reverse("notification_list"))
        self.assertEqual(other_response.status_code, 200)
        self.assertNotContains(other_response, self.notification.title)



    def test_unread_count_counts_multiple_notifications_with_duplicate_content(self):
        for _ in range(2):
            UserNotification.objects.create(
                recipient=self.recipient,
                actor=self.other,
                title=self.notification.title,
                body=self.notification.body,
                target_url=self.notification.target_url,
            )
        self.notification.mark_read(user=self.recipient)

        client = Client()
        client.force_login(self.recipient)
        response = client.get(reverse("notification_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["unread_notification_count"], 2)
        self.assertEqual(len(response.context["notifications"]), 2)

    def test_active_position_holder_can_access_notifications_for_assigned_tasks(self):
        user = User.objects.create_user(
            username="notification-position-holder",
            password="StrongPass!2026",
            must_change_password=False,
        )
        unit = OrganizationalUnit.objects.create(
            code="NOTICE-UNIT",
            name="واحد دریافت‌کننده اعلان",
        )
        position = OrganizationalPosition.objects.create(
            unit=unit,
            code="NOTICE-SPECIALIST",
            title="کارشناس",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        PositionAssignment.objects.create(
            user=user,
            unit=unit,
            position=position,
            valid_from=timezone.localdate(),
            is_active=True,
            reason="انتصاب برای دریافت وظایف داخلی",
        )
        UserNotification.objects.create(
            recipient=user,
            actor=self.other,
            title="وظیفه جدید",
            body="یک وظیفه برای اقدام به شما تخصیص داده شده است.",
            target_url="/tasks/1/",
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse("notification_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وظیفه جدید")
        self.assertEqual(response.context["unread_notification_count"], 1)

    def test_user_without_operational_role_cannot_access_notification_inbox_or_see_menu_link(self):
        unauthorized = User.objects.create_user(
            username="notification-no-role", password="StrongPass!2026", role="",
            must_change_password=False,
        )
        client = Client()
        client.force_login(unauthorized)
        response = client.get(reverse("notification_list"))
        self.assertEqual(response.status_code, 403)
        dashboard = client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, reverse("notification_list"))

    def test_recipient_can_mark_notification_read_and_is_redirected_to_internal_target(self):
        client = Client()
        client.force_login(self.recipient)
        response = client.post(
            reverse("notification_mark_read", args=[self.notification.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.notification.target_url)
        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_other_user_cannot_read_or_mutate_another_users_notification(self):
        client = Client()
        client.force_login(self.other)
        response = client.post(
            reverse("notification_mark_read", args=[self.notification.pk])
        )
        self.assertEqual(response.status_code, 404)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            UserNotification.objects.filter(pk=self.notification.pk).update(read_at=None)
