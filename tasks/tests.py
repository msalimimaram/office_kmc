from django.test import TestCase

from accounts.models import User
from organizations.models import Company
from requests_portal.models import ServiceRequest
from tasks.forms import InternalTaskForm


class InternalTaskFormScopeTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="TASK-A", name="شرکت آزمایشی")
        self.employee = User.objects.create_user(
            username="task-employee", password="StrongPass!2026",
            role="employee", company=self.company, must_change_password=False,
        )
        self.head = User.objects.create_user(
            username="task-head", password="StrongPass!2026",
            role="department_head", must_change_password=False,
        )
        self.specialist = User.objects.create_user(
            username="task-specialist", password="StrongPass!2026",
            role="insurance_specialist", must_change_password=False,
        )
        self.public_request = ServiceRequest.objects.create(
            reference="IB-TASK-PUBLIC", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.employee, company=self.company,
            title="درخواست عمومی", description="شرح",
        )
        self.confidential_request = ServiceRequest.objects.create(
            reference="IB-TASK-SECRET", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.employee, company=self.company,
            title="درخواست محرمانه", description="شرح محرمانه", is_confidential=True,
        )

    def test_specialist_form_excludes_confidential_requests(self):
        form = InternalTaskForm(user=self.specialist)
        request_ids = set(form.fields["related_request"].queryset.values_list("pk", flat=True))
        self.assertIn(self.public_request.pk, request_ids)
        self.assertNotIn(self.confidential_request.pk, request_ids)

    def test_head_form_can_link_confidential_request(self):
        form = InternalTaskForm(user=self.head)
        request_ids = set(form.fields["related_request"].queryset.values_list("pk", flat=True))
        self.assertIn(self.confidential_request.pk, request_ids)

    def test_task_assignees_exclude_ordinary_employees(self):
        form = InternalTaskForm(user=self.head)
        assignee_ids = set(form.fields["assignees"].queryset.values_list("pk", flat=True))
        self.assertIn(self.specialist.pk, assignee_ids)
        self.assertNotIn(self.employee.pk, assignee_ids)

    def test_confidential_request_task_cannot_be_assigned_to_specialist(self):
        form = InternalTaskForm(data={
            "title": "وظیفه محرمانه",
            "description": "شرح محرمانه",
            "assignees": [str(self.specialist.pk)],
            "priority": "normal",
            "related_request": str(self.confidential_request.pk),
        }, user=self.head)
        self.assertFalse(form.is_valid())
        self.assertIn("assignees", form.errors)
