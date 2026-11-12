from datetime import date, timedelta

from django.db import models

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    User, UserNotification, RoleAssignment,
    OrganizationalUnit, OrganizationalPosition, PositionAssignment,
)
from organizations.models import Company, Person
from claims.models import Claim


class SubsidiaryRepresentativeAssignmentIntegrityTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.company_a = Company.objects.create(
            code="REP-LIMIT-A",
            name="شرکت سقف نمایندگی",
        )
        self.company_b = Company.objects.create(
            code="REP-LIMIT-B",
            name="شرکت دوم نمایندگی",
        )

    def _user(self, username):
        return User.objects.create_user(
            username=username,
            password="StrongPass!2026",
            must_change_password=False,
        )

    def _assignment(self, user, company, **kwargs):
        # Test identities use the legacy company link where a full HR person
        # record is intentionally outside this focused scope test.
        if not user.company_id and not RoleAssignment.objects.filter(
            user=user, role=RoleAssignment.Role.SUBSIDIARY_REP, is_active=True
        ).exists():
            user.company = company
            user.save(update_fields=["company"])
        elif not RoleAssignment.objects.filter(
            user=user, role=RoleAssignment.Role.SUBSIDIARY_REP, is_active=True,
            valid_from__lte=kwargs.get("valid_until") or date.max,
        ).filter(
            models.Q(valid_until__isnull=True)
            | models.Q(valid_until__gte=kwargs.get("valid_from") or self.today)
        ).exists():
            user.company = company
            user.save(update_fields=["company"])
        defaults = {
            "user": user,
            "role": RoleAssignment.Role.SUBSIDIARY_REP,
            "company": company,
            "line_code": "health",
            "valid_from": self.today,
            "reason": "انتصاب نماینده برای آزمون محدودیت دامنه",
        }
        defaults.update(kwargs)
        return RoleAssignment.objects.create(**defaults)

    def test_company_representative_must_be_linked_to_the_same_company(self):
        user = self._user("rep-wrong-company")
        user.company = self.company_a
        user.save(update_fields=["company"])
        with self.assertRaises(ValidationError) as raised:
            RoleAssignment.objects.create(
                user=user, role=RoleAssignment.Role.SUBSIDIARY_REP,
                company=self.company_b, line_code="health",
                valid_from=self.today,
                reason="تلاش برای انتصاب در شرکت نامرتبط",
            )
        self.assertIn("company", raised.exception.message_dict)

    def test_company_representative_requires_company_identity_when_no_person_record_exists(self):
        user = self._user("rep-without-company-identity")
        with self.assertRaises(ValidationError) as raised:
            RoleAssignment.objects.create(
                user=user, role=RoleAssignment.Role.SUBSIDIARY_REP,
                company=self.company_a, line_code="health",
                valid_from=self.today,
                reason="تلاش برای انتصاب بدون هویت شرکتی",
            )
        self.assertIn("company", raised.exception.message_dict)

    def test_dependent_representative_must_be_covered_by_primary_employee_employment(self):
        from organizations.models import Person, PersonEmployment
        employee = Person.objects.create(
            company=self.company_a, national_id="1111111111",
            first_name="کارمند", last_name="اصلی",
            birth_date=self.today - timedelta(days=12000),
        )
        PersonEmployment.objects.create(
            person=employee, company=self.company_a,
            valid_from=self.today - timedelta(days=30),
            valid_until=self.today + timedelta(days=10),
            status=PersonEmployment.Status.ACTIVE,
        )
        dependent_user = self._user("rep-dependent")
        Person.objects.create(
            company=self.company_a, user=dependent_user, employee=employee,
            relationship=Person.Relationship.SPOUSE,
            national_id="2222222222", first_name="همسر", last_name="کارمند",
            birth_date=self.today - timedelta(days=11000),
        )
        with self.assertRaises(ValidationError) as raised:
            RoleAssignment.objects.create(
                user=dependent_user, role=RoleAssignment.Role.SUBSIDIARY_REP,
                company=self.company_a, line_code="health",
                valid_from=self.today,
                valid_until=self.today + timedelta(days=20),
                reason="انتصاب خارج از بازه اشتغال کارمند اصلی",
            )
        self.assertIn("company", raised.exception.message_dict)

    def test_company_limit_counts_distinct_users_not_line_assignments(self):
        first = self._user("rep-limit-first")
        second = self._user("rep-limit-second")
        third = self._user("rep-limit-third")
        fourth = self._user("rep-limit-fourth")

        self._assignment(first, self.company_a, line_code="health")
        self._assignment(first, self.company_a, line_code="motor")
        self._assignment(second, self.company_a)
        self._assignment(third, self.company_a)

        with self.assertRaises(ValidationError) as raised:
            self._assignment(fourth, self.company_a)

        self.assertIn("company", raised.exception.message_dict)

    def test_overlapping_multi_company_assignment_requires_system_admin_approval(self):
        representative = self._user("rep-multi-company")
        self._assignment(
            representative,
            self.company_a,
            valid_from=self.today,
            valid_until=self.today + timedelta(days=10),
        )

        with self.assertRaises(ValidationError) as missing_approval:
            self._assignment(
                representative,
                self.company_b,
                line_code="motor",
                valid_from=self.today + timedelta(days=5),
                valid_until=self.today + timedelta(days=20),
            )
        self.assertIn("approved_by", missing_approval.exception.message_dict)

        non_admin = self._user("rep-multi-company-non-admin")
        with self.assertRaises(ValidationError) as invalid_approval:
            self._assignment(
                representative,
                self.company_b,
                line_code="motor",
                valid_from=self.today + timedelta(days=5),
                valid_until=self.today + timedelta(days=20),
                approved_by=non_admin,
            )
        self.assertIn("approved_by", invalid_approval.exception.message_dict)

        administrator = self._user("rep-multi-company-admin")
        RoleAssignment.objects.create(
            user=administrator,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            valid_from=self.today,
            reason="مدیر سامانه برای تأیید استثنای چندشرکتی",
        )
        approved = self._assignment(
            representative,
            self.company_b,
            line_code="motor",
            valid_from=self.today + timedelta(days=5),
            valid_until=self.today + timedelta(days=20),
            approved_by=administrator,
            reason="استثنای موردی با تأیید مدیر سامانه؛ شرکت و رشته محدود و زمان‌دار",
        )
        self.assertEqual(approved.approved_by_id, administrator.pk)

    def test_sequential_company_appointments_do_not_require_multi_company_exception(self):
        representative = self._user("rep-sequential-company")
        self._assignment(
            representative,
            self.company_a,
            valid_from=self.today - timedelta(days=10),
            valid_until=self.today,
        )
        next_assignment = self._assignment(
            representative,
            self.company_b,
            valid_from=self.today + timedelta(days=1),
            valid_until=self.today + timedelta(days=30),
        )
        self.assertEqual(next_assignment.company_id, self.company_b.pk)


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


class LoginEligibilityTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="LOGIN-ELIGIBLE", name="شرکت ورود آزمایشی")

    def _insured_user(self, username, *, is_insured=True):
        user = User.objects.create_user(
            username=username, password="StrongPass!2026",
            role="employee", company=self.company,
            must_change_password=False,
        )
        person = Person.objects.create(
            company=self.company, user=user, national_id=f"{user.pk:010d}",
            first_name="بیمه‌شده", last_name="آزمایشی",
            birth_date=timezone.localdate() - timedelta(days=12000),
            is_insured=is_insured,
        )
        RoleAssignment.objects.create(
            user=user, role=RoleAssignment.Role.INSURED_PERSON,
            company=self.company, line_code="*",
            reason="انتصاب بیمه‌شده برای آزمون احراز صلاحیت ورود",
        )
        return user, person

    def test_person_record_without_active_or_historical_insurance_is_not_login_eligible(self):
        user, _person = self._insured_user("login-no-policy", is_insured=False)
        client = Client()
        response = client.post(reverse("login"), {
            "username": user.username, "password": "StrongPass!2026",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سابقه بیمه‌ای مجاز")
        self.assertNotIn("_auth_user_id", client.session)

    def test_currently_insured_person_can_login(self):
        user, _person = self._insured_user("login-current-insured", is_insured=True)
        client = Client()
        response = client.post(reverse("login"), {
            "username": user.username, "password": "StrongPass!2026",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(client.session["_auth_user_id"]), user.pk)

    def test_former_insured_person_with_claim_history_can_login(self):
        user, person = self._insured_user("login-former-insured", is_insured=False)
        Claim.objects.create(
            claim_number="LOGIN-HISTORY-001", person=person,
            service_type="سابقه خسارت درمان",
        )
        client = Client()
        response = client.post(reverse("login"), {
            "username": user.username, "password": "StrongPass!2026",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(client.session["_auth_user_id"]), user.pk)


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
        self.assertEqual(len(response.context["notifications"]), 3)
        self.assertEqual(
            sum(notification.read_at is None for notification in response.context["notifications"]),
            2,
        )

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

    def test_inactive_position_does_not_grant_notification_access_or_menu_link(self):
        for disabled_target in ("position", "unit"):
            with self.subTest(disabled_target=disabled_target):
                user = User.objects.create_user(
                    username=f"notification-inactive-{disabled_target}",
                    password="StrongPass!2026",
                    must_change_password=False,
                )
                unit = OrganizationalUnit.objects.create(
                    code=f"NOTICE-INACTIVE-{disabled_target.upper()}",
                    name="واحد غیرفعال",
                )
                position = OrganizationalPosition.objects.create(
                    unit=unit,
                    code=f"NOTICE-INACTIVE-POS-{disabled_target.upper()}",
                    title="سمت غیرفعال",
                    level=OrganizationalPosition.Level.SPECIALIST,
                )
                PositionAssignment.objects.create(
                    user=user,
                    unit=unit,
                    position=position,
                    valid_from=timezone.localdate(),
                    is_active=True,
                    reason="آزمون رد دسترسی سمت غیرفعال",
                )
                if disabled_target == "position":
                    position.is_active = False
                    position.save(update_fields=["is_active"])
                else:
                    unit.is_active = False
                    unit.save(update_fields=["is_active"])

                client = Client()
                client.force_login(user)
                response = client.get(reverse("notification_list"))
                self.assertEqual(response.status_code, 403)
                dashboard = client.get(reverse("dashboard"))
                self.assertNotContains(dashboard, reverse("notification_list"))

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


class AdminBusinessRoleBoundaryTests(TestCase):
    def test_superuser_without_active_business_role_cannot_open_admin(self):
        user = User.objects.create_superuser(
            username="technical-superuser-only", email="technical-superuser@example.invalid",
            password="StrongPass!2026",
        )
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get("/admin/").status_code, 403)

    def test_active_department_head_can_open_admin_without_superuser_flag(self):
        user = User.objects.create_user(
            username="business-head-admin", password="StrongPass!2026",
            is_staff=True, must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=user, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="دسترسی مدیریتی بر اساس انتصاب معتبر",
        )
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get("/admin/").status_code, 200)

    def test_staff_flag_without_global_role_cannot_open_admin(self):
        user = User.objects.create_user(
            username="staff-no-business-role", password="StrongPass!2026",
            is_staff=True, must_change_password=False,
        )
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get("/admin/").status_code, 403)

    def test_future_global_appointment_sets_technical_staff_flag_but_not_early_access(self):
        user = User.objects.create_user(
            username="future-head-admin", password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=user, role=RoleAssignment.Role.DEPARTMENT_HEAD,
            valid_from=timezone.localdate() + timedelta(days=1),
            reason="انتصاب آتی رئیس اداره",
        )
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get("/admin/").status_code, 403)
