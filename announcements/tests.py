from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from organizations.models import Company
from announcements.models import Announcement
from announcements.views import _visible_announcements


class AnnouncementVisibilityTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="AN-A", name="شرکت الف")
        self.company_b = Company.objects.create(code="AN-B", name="شرکت ب")
        self.employee = User.objects.create_user(
            username="ann-employee", password="StrongPass!2026",
            role="employee", company=self.company_a,
        )
        self.admin = User.objects.create_user(username="ann-admin", password="StrongPass!2026", role="system_admin", must_change_password=False)
        now = timezone.now()
        Announcement.objects.create(
            title="اطلاعیه عمومی", body="متن", audience=Announcement.Audience.ALL,
            is_published=True, publish_at=now - timedelta(minutes=1), created_by=self.admin,
        )
        Announcement.objects.create(
            title="اطلاعیه شرکت دیگر", body="متن", audience=Announcement.Audience.ALL,
            company=self.company_b, is_published=True, publish_at=now - timedelta(minutes=1),
        )
        Announcement.objects.create(
            title="پیش‌نویس", body="متن", audience=Announcement.Audience.ALL,
            is_published=False, publish_at=now - timedelta(minutes=1),
        )
        Announcement.objects.create(
            title="اطلاعیه منقضی", body="متن", audience=Announcement.Audience.ALL,
            is_published=True, publish_at=now - timedelta(days=2), expires_at=now - timedelta(days=1), created_by=self.admin,
        )

    def test_employee_sees_only_published_current_announcements_for_their_scope(self):
        titles = set(_visible_announcements(self.employee).values_list("title", flat=True))
        self.assertEqual(titles, {"اطلاعیه عمومی"})
