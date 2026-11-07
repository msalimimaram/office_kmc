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



class CorrespondenceFollowUpFlowTests(TestCase):
    def setUp(self):
        from accounts.models import User
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
