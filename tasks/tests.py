from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import (
    RoleAssignment, User, UserNotification,
    OrganizationalUnit, OrganizationalPosition, PositionAssignment,
)
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


class OrganizationalTaskScopeTests(TestCase):
    def setUp(self):
        from django.utils import timezone

        self.parent = OrganizationalUnit.objects.create(
            code="TASK-ROOT",
            name="واحد بالادست",
        )
        self.child = OrganizationalUnit.objects.create(
            code="TASK-CHILD",
            name="واحد زیرمجموعه",
            parent=self.parent,
        )
        self.other_unit = OrganizationalUnit.objects.create(
            code="TASK-OTHER",
            name="واحد مستقل",
        )
        self.supervisor_position = OrganizationalPosition.objects.create(
            unit=self.parent,
            code="TASK-SUPERVISOR",
            title="سرپرست آزمون",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        self.specialist_position = OrganizationalPosition.objects.create(
            unit=self.child,
            code="TASK-SPECIALIST",
            title="کارشناس آزمون",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        self.other_position = OrganizationalPosition.objects.create(
            unit=self.other_unit,
            code="TASK-OTHER-SPECIALIST",
            title="کارشناس واحد دیگر",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        self.manager = User.objects.create_user(
            username="task-tree-supervisor",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.subordinate = User.objects.create_user(
            username="task-tree-subordinate",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.outsider = User.objects.create_user(
            username="task-tree-outsider",
            password="StrongPass!2026",
            must_change_password=False,
        )
        PositionAssignment.objects.create(
            user=self.manager, unit=self.parent, position=self.supervisor_position,
            valid_from=timezone.localdate(), reason="سرپرست واحد بالادست",
        )
        PositionAssignment.objects.create(
            user=self.subordinate, unit=self.child, position=self.specialist_position,
            valid_from=timezone.localdate(), reason="کارشناس واحد زیرمجموعه",
        )
        PositionAssignment.objects.create(
            user=self.outsider, unit=self.other_unit, position=self.other_position,
            valid_from=timezone.localdate(), reason="کارشناس واحد مستقل",
        )
        RoleAssignment.objects.create(
            user=self.subordinate,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="انتصاب تخصصی",
        )
        RoleAssignment.objects.create(
            user=self.outsider,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="انتصاب تخصصی خارج از واحد",
        )

    def test_supervisor_can_assign_only_to_active_subordinates_in_descendant_units(self):
        form = InternalTaskForm(user=self.manager)
        choices = set(form.fields["assignees"].queryset.values_list("pk", flat=True))
        self.assertIn(self.subordinate.pk, choices)
        self.assertNotIn(self.outsider.pk, choices)
        self.assertNotIn(self.manager.pk, choices)

    def test_supervisor_sees_subordinate_tasks_but_not_independent_unit_tasks(self):
        from tasks.views import _visible_tasks

        subordinate_task = InternalTask.objects.create(
            title="وظیفه واحد زیرمجموعه",
            description="برای آزمون محدوده",
            created_by=self.subordinate,
        )
        subordinate_task.assignees.add(self.subordinate)
        outsider_task = InternalTask.objects.create(
            title="وظیفه واحد مستقل",
            description="نباید در صف سرپرست باشد",
            created_by=self.outsider,
        )
        outsider_task.assignees.add(self.outsider)

        visible_ids = set(_visible_tasks(self.manager).values_list("pk", flat=True))
        self.assertIn(subordinate_task.pk, visible_ids)
        self.assertNotIn(outsider_task.pk, visible_ids)


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

    def test_new_task_assignment_notifies_each_assignee_and_opens_task(self):
        client = Client()
        client.force_login(self.head)
        response = client.post(reverse("task_create"), {
            "title": "وظیفه جدید برای اعلان",
            "description": "شرح اقدام مورد انتظار",
            "assignees": [str(self.assignee.pk)],
            "priority": InternalTask.Priority.HIGH,
            "due_at": "",
            "related_request": "",
        })
        self.assertEqual(response.status_code, 302)
        task = InternalTask.objects.get(title="وظیفه جدید برای اعلان")
        notice = UserNotification.objects.get(
            recipient=self.assignee,
            target_url=reverse("task_update", args=[task.pk]),
            title="وظیفه جدید به شما واگذار شد",
        )
        self.assertEqual(notice.actor_id, self.head.pk)

        client.force_login(self.assignee)
        self.assertEqual(client.get(reverse("task_update", args=[task.pk])).status_code, 200)
        inbox = client.get(reverse("notification_list"))
        self.assertEqual(inbox.status_code, 200)
        self.assertContains(inbox, "وظیفه جدید به شما واگذار شد")

    def test_task_status_change_notifies_creator(self):
        client = Client()
        client.force_login(self.assignee)
        response = client.post(reverse("task_update", args=[self.task.pk]), {
            "status": InternalTask.Status.IN_PROGRESS,
            "note": "اقدام آغاز شد",
        })
        self.assertEqual(response.status_code, 302)
        notice = UserNotification.objects.get(
            recipient=self.head,
            actor=self.assignee,
            target_url=reverse("task_update", args=[self.task.pk]),
            title="وضعیت وظیفه به‌روزرسانی شد",
        )
        self.assertIn("در حال انجام", notice.body)

    def test_each_assignee_gets_their_own_first_view_and_first_action_events(self):
        co_assignee = User.objects.create_user(
            username="task-event-co-assignee",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=co_assignee,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="مسئول دوم وظیفه",
        )
        self.task.assignees.add(co_assignee)
        client = Client()
        client.force_login(co_assignee)
        url = reverse("task_update", args=[self.task.pk])

        self.assertEqual(client.get(url).status_code, 200)
        self.assertEqual(client.post(url, {
            "status": InternalTask.Status.IN_PROGRESS,
            "note": "اقدام مسئول دوم",
        }).status_code, 302)

        self.assertTrue(self.task.events.filter(
            event_type=TaskEvent.EventType.FIRST_VIEWED,
            actor=co_assignee,
        ).exists())
        self.assertTrue(self.task.events.filter(
            event_type=TaskEvent.EventType.FIRST_ACTION,
            actor=co_assignee,
        ).exists())
        self.assertEqual(
            self.task.events.filter(event_type=TaskEvent.EventType.FIRST_VIEWED).count(),
            1,
        )
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
