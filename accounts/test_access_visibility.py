from datetime import timedelta

from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.context_processors import access_flags
from accounts.models import RoleAssignment, User
from insurance.models import Insurer
from organizations.models import Company


class AccessNavigationVisibilityTests(TestCase):
    """Regression tests for role-derived navigation visibility."""

    def setUp(self):
        self.factory = RequestFactory()
        self.today = timezone.localdate()

    def request_for(self, user):
        request = self.factory.get("/")
        request.user = user
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def flags_for(self, user):
        return access_flags(self.request_for(user))["access"]

    def render_sidebar(self, user):
        return render_to_string("base.html", {}, request=self.request_for(user))

    def user(self, username, **kwargs):
        return User.objects.create_user(
            username=username,
            password=None,
            must_change_password=False,
            **kwargs,
        )

    def assign(self, user, role, **kwargs):
        return RoleAssignment.objects.create(
            user=user,
            role=role,
            valid_from=self.today,
            reason="انتصاب صریح برای آزمون نمایش قابلیت‌ها",
            **kwargs,
        )

    def test_anonymous_request_has_no_navigation_capabilities(self):
        request = self.factory.get("/")
        request.user = type("Anonymous", (), {"is_authenticated": False})()
        result = access_flags(request)
        self.assertEqual(result["access"], {})
        self.assertEqual(result["unread_notification_count"], 0)

    def test_superuser_flag_alone_does_not_expose_business_navigation(self):
        user = self.user("visibility-superuser-only", is_superuser=True, is_staff=True)
        flags = self.flags_for(user)
        for capability in (
            "notifications", "workflow", "delegation_manage", "claims",
            "contracts", "assets", "correspondence", "requests", "documents",
            "people", "tasks", "imports", "reports", "leadership_titles",
        ):
            with self.subTest(capability=capability):
                self.assertFalse(flags[capability])

    def test_expired_assignment_does_not_restore_legacy_role_or_navigation(self):
        user = self.user(
            "visibility-expired-specialist",
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
        )
        self.assign(
            user,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            valid_from=self.today - timedelta(days=30),
            valid_until=self.today - timedelta(days=1),
            line_code="health",
        )
        flags = self.flags_for(user)
        self.assertFalse(flags["staff"])
        self.assertFalse(flags["workflow"])
        self.assertFalse(flags["claims"])
        self.assertFalse(flags["imports"])
        self.assertFalse(flags["reports"])

    def test_department_head_receives_department_oversight_navigation(self):
        user = self.user("visibility-department-head")
        self.assign(user, RoleAssignment.Role.DEPARTMENT_HEAD)
        flags = self.flags_for(user)
        self.assertTrue(flags["global"])
        self.assertTrue(flags["workflow"])
        self.assertTrue(flags["delegation_manage"])
        self.assertTrue(flags["reports"])
        self.assertTrue(flags["imports"])
        html = self.render_sidebar(user)
        self.assertIn("صندوق گردش‌کار", html)
        self.assertIn("مدیریت تفویض اختیار", html)
        self.assertIn("گزارش‌های مدیریتی", html)

    def test_insured_person_gets_personal_services_not_staff_operations(self):
        user = self.user("visibility-insured")
        self.assign(user, RoleAssignment.Role.INSURED_PERSON, line_code="*")
        flags = self.flags_for(user)
        self.assertTrue(flags["notifications"])
        self.assertTrue(flags["requests"])
        self.assertTrue(flags["claims"])
        self.assertTrue(flags["people"])
        self.assertTrue(flags["documents"])
        self.assertTrue(flags["assets"])
        self.assertFalse(flags["workflow"])
        self.assertFalse(flags["tasks"])
        self.assertFalse(flags["imports"])
        self.assertFalse(flags["reports"])
        self.assertFalse(flags["delegation_manage"])
        html = self.render_sidebar(user)
        self.assertIn("درخواست‌ها", html)
        self.assertIn("خسارت‌ها", html)
        self.assertIn("دارایی‌ها", html)
        self.assertNotIn("صندوق گردش‌کار", html)
        self.assertNotIn("وظایف", html)
        self.assertNotIn("ورود اکسل", html)
        self.assertNotIn("گزارش‌های مدیریتی", html)

    def test_specialist_receives_operational_workflow_and_processing_navigation(self):
        user = self.user("visibility-specialist")
        self.assign(
            user,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
        )
        flags = self.flags_for(user)
        self.assertTrue(flags["staff"])
        self.assertTrue(flags["workflow"])
        self.assertTrue(flags["claims"])
        self.assertTrue(flags["contracts"])
        self.assertTrue(flags["imports"])
        self.assertTrue(flags["reports"])
        self.assertFalse(flags["delegation_manage"])

    def test_company_representative_receives_company_scoped_navigation(self):
        company = Company.objects.create(
            code="VISIBILITY-COMPANY",
            name="شرکت آزمون نمایش",
        )
        user = self.user("visibility-company-rep", company=company)
        self.assign(
            user,
            RoleAssignment.Role.SUBSIDIARY_REP,
            company=company,
            line_code="*",
        )
        flags = self.flags_for(user)
        self.assertTrue(flags["company_rep"])
        self.assertTrue(flags["requests"])
        self.assertTrue(flags["claims"])
        self.assertTrue(flags["people"])
        self.assertTrue(flags["assets"])
        self.assertFalse(flags["delegation_manage"])
        self.assertFalse(flags["imports"])

    def test_insurer_representative_receives_insurer_scoped_navigation(self):
        insurer = Insurer.objects.create(name="بیمه‌گر آزمون نمایش")
        user = self.user("visibility-insurer-rep")
        self.assign(
            user,
            RoleAssignment.Role.INSURER_REP,
            insurer=insurer,
        )
        flags = self.flags_for(user)
        self.assertTrue(flags["insurer_rep"])
        self.assertTrue(flags["requests"])
        self.assertTrue(flags["claims"])
        self.assertTrue(flags["contracts"])
        self.assertTrue(flags["assets"])
        self.assertTrue(flags["correspondence"])
        self.assertTrue(flags["imports"])
        self.assertFalse(flags["delegation_manage"])
        self.assertFalse(flags["reports"])

    def test_multiple_active_roles_produce_union_of_capabilities(self):
        user = self.user("visibility-multi-role")
        self.assign(user, RoleAssignment.Role.INSURED_PERSON, line_code="*")
        self.assign(
            user,
            RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
        )
        flags = self.flags_for(user)
        self.assertTrue(flags["insured"])
        self.assertTrue(flags["staff"])
        self.assertTrue(flags["workflow"])
        self.assertTrue(flags["requests"])
        self.assertTrue(flags["claims"])
        self.assertTrue(flags["imports"])
        self.assertTrue(flags["reports"])
        html = self.render_sidebar(user)
        self.assertIn("صندوق گردش‌کار", html)
        self.assertIn("ورود اکسل", html)
