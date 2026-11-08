from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company
from requests_portal.models import ServiceRequest
from tasks.forms import InternalTaskForm
from tasks.models import InternalTask, TaskEvent


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
        RoleAssignment.objects.create(user=self.head, role=RoleAssignment.Role.DEPARTMENT_HEAD)
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="*",
        )
        self.public_request = ServiceRequest.objects.create(
            reference="IB-TASK-PUBLIC", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.employee, company=self.company,
            assigned_to=self.specialist,
            title="درخواست عمومی", description="شرح",
        )
        self.confidential_request = ServiceRequest.objects.create(
            reference="IB-TASK-SECRET", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.employee, company=self.company,
            title="درخواست محرمانه", description="شرح محرمانه", is_confidential=True,
        )

    def _confidential_task_form(self, assignee_ids):
        return InternalTaskForm(data={
            "title": "وظیفه محرمانه",
            "description": "شرح محرمانه",
            "assignees": [str(pk) for pk in assignee_ids],
            "priority": "normal",
            "related_request": str(self.confidential_request.pk),
        }, user=self.head)

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
        form = self._confidential_task_form([self.specialist.pk])
        self.assertFalse(form.is_valid())
        self.assertIn("assignees", form.errors)

    def test_confidential_request_task_can_be_assigned_to_department_head(self):
        form = self._confidential_task_form([self.head.pk])
        self.assertTrue(form.is_valid(), form.errors)


class TaskFirstViewActionFlowTests(TestCase):
    def setUp(self):
        self.head = User.objects.create_user(
            username="task-event-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="مدیر برای آزمون رویداد وظیفه",
        )
        self.assignee = User.objects.create_user(
            username="task-event-assignee",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.assignee,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس برای آزمون رویداد وظیفه",
        )
        self.task = InternalTask.objects.create(
            title="وظیفه ثبت اولین مشاهده",
            description="آزمون ثبت زمان مشاهده و اقدام",
            created_by=self.head,
            priority=InternalTask.Priority.NORMAL,
            status=InternalTask.Status.OPEN,
        )
        self.task.assignees.add(self.assignee)

    def test_first_view_is_recorded_once_for_the_first_viewer(self):
        client = Client()
        client.force_login(self.assignee)
        url = reverse("task_update", args=[self.task.pk])

        first = client.get(url)
        self.assertEqual(first.status_code, 200)
        second = client.get(url)
        self.assertEqual(second.status_code, 200)

        events = self.task.events.filter(event_type=TaskEvent.EventType.FIRST_VIEWED)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().actor_id, self.assignee.pk)

    def test_first_valid_status_change_records_first_action_once(self):
        client = Client()
        client.force_login(self.assignee)
        url = reverse("task_update", args=[self.task.pk])
        self.assertEqual(client.get(url).status_code, 200)

        response = client.post(url, {
            "status": InternalTask.Status.IN_PROGRESS,
            "note": "کار آغاز شد",
        })
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, InternalTask.Status.IN_PROGRESS)
        event = self.task.events.get(event_type=TaskEvent.EventType.FIRST_ACTION)
        self.assertEqual(event.actor_id, self.assignee.pk)

        client.post(url, {
            "status": InternalTask.Status.WAITING,
            "note": "در انتظار پاسخ",
        })
        self.assertEqual(
            self.task.events.filter(event_type=TaskEvent.EventType.FIRST_ACTION).count(),
            1,
        )

    def test_invalid_transition_does_not_record_first_action(self):
        client = Client()
        client.force_login(self.assignee)
        url = reverse("task_update", args=[self.task.pk])
        client.get(url)

        response = client.post(url, {
            "status": InternalTask.Status.DONE,
            "note": "پرش غیرمجاز",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            self.task.events.filter(event_type=TaskEvent.EventType.FIRST_ACTION).exists()
        )
