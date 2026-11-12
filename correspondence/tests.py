from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from organizations.models import Company
from insurance.models import Insurer
from correspondence.models import Correspondence
from correspondence.services import next_internal_number
from correspondence.views import _scope


class CorrespondenceScopeTests(TestCase):
    def setUp(self):
        self.company_a = Company.objects.create(code="COR-A", name="شرکت الف")
        self.company_b = Company.objects.create(code="COR-B", name="شرکت ب")
        self.insurer = Insurer.objects.create(name="بیمه‌گر الف")
        self.rep = User.objects.create_user(username="cor-rep", password="StrongPass!2026", must_change_password=False, role="subsidiary_rep", company=self.company_a)
        self.insurer_user = User.objects.create_user(username="cor-ins", password="StrongPass!2026", must_change_password=False, role="insurer", insurer=self.insurer)
        self._create_correspondence(subject="مکاتبه الف", channel="email", direction="inbound", company=self.company_a, insurer=self.insurer, summary="شرح", created_by=self.rep)
        self._create_correspondence(subject="مکاتبه ب", channel="email", direction="inbound", company=self.company_b, insurer=self.insurer, summary="شرح", created_by=self.rep)
        self._create_correspondence(subject="محرمانه", channel="phone", direction="internal", company=self.company_a, summary="شرح", is_confidential=True, created_by=self.rep)

    def _create_correspondence(self, **kwargs):
        kwargs["internal_number"] = next_internal_number()
        return Correspondence.objects.create(**kwargs)

    def test_subsidiary_representative_sees_only_nonconfidential_company_records(self):
        subjects = set(_scope(self.rep).values_list("subject", flat=True))
        self.assertEqual(subjects, {"مکاتبه الف"})

    def test_insurer_sees_only_records_linked_to_their_insurer(self):
        subjects = set(_scope(self.insurer_user).values_list("subject", flat=True))
        self.assertEqual(subjects, {"مکاتبه الف", "مکاتبه ب"})




class CorrespondenceOrganizationalScopeTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        from accounts.models import (
            OrganizationalUnit, OrganizationalPosition, PositionAssignment,
            RoleAssignment, User,
        )

        self.parent = OrganizationalUnit.objects.create(
            code="COR-ROOT",
            name="واحد مکاتبات بالادست",
        )
        self.child = OrganizationalUnit.objects.create(
            code="COR-CHILD",
            name="واحد مکاتبات زیرمجموعه",
            parent=self.parent,
        )
        self.outside = OrganizationalUnit.objects.create(
            code="COR-OUTSIDE",
            name="واحد مکاتبات مستقل",
        )
        self.supervisor_position = OrganizationalPosition.objects.create(
            unit=self.parent,
            code="COR-SUPERVISOR",
            title="سرپرست مکاتبات",
            level=OrganizationalPosition.Level.SUPERVISOR,
        )
        self.specialist_position = OrganizationalPosition.objects.create(
            unit=self.child,
            code="COR-SPECIALIST",
            title="کارشناس مکاتبات",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        self.outside_position = OrganizationalPosition.objects.create(
            unit=self.outside,
            code="COR-OUTSIDE-SPECIALIST",
            title="کارشناس مستقل",
            level=OrganizationalPosition.Level.SPECIALIST,
        )
        self.manager = User.objects.create_user(
            username="cor-tree-supervisor",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.subordinate = User.objects.create_user(
            username="cor-tree-subordinate",
            password="StrongPass!2026",
            must_change_password=False,
        )
        self.outsider = User.objects.create_user(
            username="cor-tree-outsider",
            password="StrongPass!2026",
            must_change_password=False,
        )
        PositionAssignment.objects.create(
            user=self.manager, unit=self.parent, position=self.supervisor_position,
            line_code="*", valid_from=timezone.localdate(), reason="سرپرست مکاتبات",
        )
        PositionAssignment.objects.create(
            user=self.subordinate, unit=self.child, position=self.specialist_position,
            line_code="health", valid_from=timezone.localdate(), reason="کارشناس زیرمجموعه",
        )
        PositionAssignment.objects.create(
            user=self.outsider, unit=self.outside, position=self.outside_position,
            line_code="health", valid_from=timezone.localdate(), reason="کارشناس واحد مستقل",
        )
        RoleAssignment.objects.create(
            user=self.subordinate,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس مجاز مکاتبات",
        )
        RoleAssignment.objects.create(
            user=self.outsider,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس واحد مستقل",
        )
        self.subordinate_item = Correspondence.objects.create(
            internal_number=next_internal_number(),
            subject="مکاتبه واحد زیرمجموعه",
            channel=Correspondence.Channel.LETTER,
            direction=Correspondence.Direction.INBOUND,
            summary="نامه واحد تحت نظارت",
            assigned_to=self.subordinate,
            created_by=self.subordinate,
        )
        self.outside_item = Correspondence.objects.create(
            internal_number=next_internal_number(),
            subject="مکاتبه واحد مستقل",
            channel=Correspondence.Channel.LETTER,
            direction=Correspondence.Direction.INBOUND,
            summary="نامه خارج از محدوده",
            assigned_to=self.outsider,
            created_by=self.outsider,
        )

    def test_supervisor_sees_correspondence_of_descendant_units_only(self):
        visible = set(_scope(self.manager).values_list("pk", flat=True))
        self.assertIn(self.subordinate_item.pk, visible)
        self.assertNotIn(self.outside_item.pk, visible)

    def test_supervisor_form_offers_only_subordinate_recipients(self):
        from correspondence.forms import CorrespondenceForm

        form = CorrespondenceForm(user=self.manager)
        recipient_ids = set(form.fields["assigned_to"].queryset.values_list("pk", flat=True))
        self.assertIn(self.subordinate.pk, recipient_ids)
        self.assertNotIn(self.outsider.pk, recipient_ids)
        self.assertNotIn(self.manager.pk, recipient_ids)

    def test_supervisor_can_create_correspondence_assigned_to_subordinate(self):
        from django.urls import reverse

        client = Client()
        client.force_login(self.manager)
        response = client.post(reverse("correspondence_create"), {
            "subject": "ارجاع مکاتبه از سرپرست",
            "channel": Correspondence.Channel.LETTER,
            "direction": Correspondence.Direction.INTERNAL,
            "summary": "برای بررسی و پیگیری به کارشناس واحد ارجاع شود.",
            "assigned_to": str(self.subordinate.pk),
            "follow_up_status": Correspondence.FollowUp.PENDING,
            "is_confidential": "",
            "attachment": "",
        })
        self.assertEqual(response.status_code, 302)
        created = Correspondence.objects.get(subject="ارجاع مکاتبه از سرپرست")
        self.assertEqual(created.created_by_id, self.manager.pk)
        self.assertEqual(created.assigned_to_id, self.subordinate.pk)


class CorrespondenceFollowUpFlowTests(TestCase):
    def setUp(self):
        from accounts.models import RoleAssignment, User
        from correspondence.models import Correspondence
        from correspondence.services import next_internal_number

        self.company = Company.objects.create(code="COR-FLOW", name="شرکت جریان مکاتبه")
        self.creator = User.objects.create_user(
            username="cor-flow-creator",
            password="StrongPass!2026",
            must_change_password=False,
            role="subsidiary_rep",
            company=self.company,
        )
        self.assignee = User.objects.create_user(
            username="cor-flow-assignee",
            password="StrongPass!2026",
            must_change_password=False,
            role="employee",
        )
        RoleAssignment.objects.create(
            user=self.assignee,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health",
            reason="کارشناس گیرنده برای آزمون ارجاع مکاتبه",
        )
        self.item = Correspondence.objects.create(
            internal_number=next_internal_number(),
            subject="پیگیری نامه بیمه‌گر",
            channel=Correspondence.Channel.LETTER,
            direction=Correspondence.Direction.INBOUND,
            company=self.company,
            summary="نامه برای بررسی و اقدام دریافت شد.",
            follow_up_status=Correspondence.FollowUp.PENDING,
            created_by=self.creator,
        )

    def test_creator_can_open_detail_and_record_follow_up_with_persisted_event(self):
        from auditlog.models import AuditEvent
        from correspondence.models import Correspondence, CorrespondenceEvent

        client = Client()
        client.force_login(self.creator)
        listing = client.get(reverse("correspondence_list"))
        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, reverse("correspondence_detail", args=[self.item.pk]))

        detail = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "تاریخچه اقدامات")

        response = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "follow_up_status": Correspondence.FollowUp.COMPLETED,
            "follow_up_due": "2026-11-20",
            "note": "پاسخ بیمه‌گر دریافت و بررسی شد.",
        })
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.follow_up_status, Correspondence.FollowUp.COMPLETED)
        self.assertEqual(self.item.follow_up_due.isoformat(), "2026-11-20")
        event = CorrespondenceEvent.objects.get(
            correspondence=self.item,
            event_type=CorrespondenceEvent.EventType.STATUS_CHANGED,
        )
        self.assertEqual(event.actor_id, self.creator.pk)
        self.assertIn("پاسخ بیمه‌گر دریافت", event.summary)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.creator,
                action="correspondence_status_changed",
                object_id=str(self.item.pk),
            ).exists()
        )

    def test_sender_cannot_act_after_correspondence_is_assigned_to_another_user(self):
        from correspondence.models import Correspondence

        self.item.assigned_to = self.assignee
        self.item.save(update_fields=["assigned_to", "updated_at"])

        client = Client()
        client.force_login(self.creator)
        detail = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, 'name="follow_up_status"')
        denied = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "follow_up_status": Correspondence.FollowUp.COMPLETED,
            "follow_up_due": "",
            "note": "اقدام توسط فرستنده",
        })
        self.assertEqual(denied.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.follow_up_status, Correspondence.FollowUp.PENDING)

    def test_explicit_assignee_can_open_and_complete_follow_up(self):
        from correspondence.models import Correspondence

        self.item.assigned_to = self.assignee
        self.item.save(update_fields=["assigned_to", "updated_at"])
        client = Client()
        client.force_login(self.assignee)
        detail = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertEqual(detail.status_code, 200)
        response = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "follow_up_status": Correspondence.FollowUp.COMPLETED,
            "follow_up_due": "",
            "note": "مسئول جاری بررسی را تکمیل کرد.",
        })
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.follow_up_status, Correspondence.FollowUp.COMPLETED)

    def test_company_representative_cannot_open_another_company_correspondence_detail(self):
        from accounts.models import User
        outsider_company = Company.objects.create(code="COR-FLOW-OTHER", name="شرکت خارج از محدوده")
        outsider = User.objects.create_user(
            username="cor-flow-outsider",
            password="StrongPass!2026",
            must_change_password=False,
            role="subsidiary_rep",
            company=outsider_company,
        )
        client = Client()
        client.force_login(outsider)
        response = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertEqual(response.status_code, 404)



class CorrespondenceLinkFlowTests(TestCase):
    def setUp(self):
        from accounts.models import RoleAssignment, User
        from correspondence.models import Correspondence, CorrespondenceLink
        from correspondence.services import next_internal_number

        self.company_a = Company.objects.create(code="COR-LINK-A", name="شرکت مقصد الف")
        self.company_b = Company.objects.create(code="COR-LINK-B", name="شرکت مقصد ب")
        self.rep = User.objects.create_user(
            username="cor-link-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.rep,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company_a,
            line_code="*",
            reason="نماینده شرکت الف برای آزمون پیوند",
        )
        self.item = Correspondence.objects.create(
            internal_number=next_internal_number(),
            subject="نامه مرتبط با شرکت",
            channel=Correspondence.Channel.LETTER,
            direction=Correspondence.Direction.INBOUND,
            company=self.company_a,
            summary="نامه برای اتصال به رکورد شرکت",
            created_by=self.rep,
        )

    def test_company_representative_can_link_company_within_scope_and_link_is_persisted(self):
        from auditlog.models import AuditEvent
        from correspondence.models import CorrespondenceLink

        client = Client()
        client.force_login(self.rep)
        detail = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "اتصال رکورد موجود")

        response = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "action": "add_link",
            "target_type": "company",
            "target_id": str(self.company_a.pk),
        })
        self.assertEqual(response.status_code, 302)
        link = CorrespondenceLink.objects.get(correspondence=self.item)
        self.assertEqual(link.content_object, self.company_a)
        self.assertEqual(link.created_by_id, self.rep.pk)
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.rep,
                action="correspondence_link_created",
                object_id=str(self.item.pk),
            ).exists()
        )
        detail = client.get(reverse("correspondence_detail", args=[self.item.pk]))
        self.assertContains(detail, "شرکت مقصد الف")

    def test_company_representative_cannot_link_company_outside_scope(self):
        from correspondence.models import CorrespondenceLink

        client = Client()
        client.force_login(self.rep)
        response = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "action": "add_link",
            "target_type": "company",
            "target_id": str(self.company_b.pk),
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CorrespondenceLink.objects.filter(correspondence=self.item).exists())

    def test_global_user_cannot_link_target_company_inconsistent_with_correspondence(self):
        from accounts.models import RoleAssignment, User
        from correspondence.models import CorrespondenceLink

        head = User.objects.create_user(
            username="cor-link-head",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=head,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="رئیس اداره برای آزمون پیوند",
        )
        client = Client()
        client.force_login(head)
        response = client.post(reverse("correspondence_detail", args=[self.item.pk]), {
            "action": "add_link",
            "target_type": "company",
            "target_id": str(self.company_b.pk),
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CorrespondenceLink.objects.filter(correspondence=self.item).exists())
