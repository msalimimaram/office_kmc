from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
from core.permissions import scoped_requests_for


class ServiceRequestTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="A", name="شرکت الف")
        self.other_company = Company.objects.create(code="B", name="شرکت ب")
        self.user = User.objects.create_user(
            username="emp", password="StrongPass!2026", must_change_password=False, role="employee", company=self.company
        )

    def test_user_can_submit_request(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": "other", "title": "درخواست آزمایشی", "description": "شرح آزمایشی"
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.first().submitted_by, self.user)

    def test_subsidiary_representative_cannot_see_confidential_or_other_company_requests(self):
        rep = User.objects.create_user(
            username="rep", password="StrongPass!2026", must_change_password=False, role="subsidiary_rep", company=self.company
        )
        ServiceRequest.objects.create(
            reference="IB-PUBLIC-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست عادی", description="شرح",
        )
        ServiceRequest.objects.create(
            reference="IB-SECRET-1", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.user, company=self.company,
            title="درخواست محرمانه", description="شرح محرمانه", is_confidential=True,
        )
        ServiceRequest.objects.create(
            reference="IB-OTHER-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.other_company,
            title="شرکت دیگر", description="شرح",
        )
        visible = set(scoped_requests_for(rep).values_list("reference", flat=True))
        self.assertIn("IB-PUBLIC-1", visible)
        self.assertNotIn("IB-SECRET-1", visible)
        self.assertNotIn("IB-OTHER-1", visible)

    def test_employee_sees_only_requests_they_submitted(self):
        ServiceRequest.objects.create(
            reference="IB-OWN-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست خودم", description="شرح",
        )
        ServiceRequest.objects.create(
            reference="IB-OTHER-2", kind=ServiceRequest.Kind.OTHER,
            submitted_by=User.objects.create_user(
                username="other-emp", password="StrongPass!2026", must_change_password=False, role="employee", company=self.other_company
            ),
            company=self.other_company, title="درخواست دیگری", description="شرح",
        )
        visible = set(scoped_requests_for(self.user).values_list("reference", flat=True))
        self.assertEqual(visible, {"IB-OWN-1"})

    def test_medical_assistance_is_visible_to_head_but_not_specialist_or_company_rep(self):
        medical = ServiceRequest.objects.create(
            reference="IB-MED-1", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.user, company=self.company,
            title="درخواست محرمانه کمک‌هزینه درمان", description="شرح محرمانه",
            is_confidential=True,
        )
        head = User.objects.create_user(
            username="head", password="StrongPass!2026", must_change_password=False, role="department_head"
        )
        specialist = User.objects.create_user(
            username="specialist", password="StrongPass!2026", must_change_password=False, role="insurance_specialist"
        )
        rep = User.objects.create_user(
            username="rep-med", password="StrongPass!2026", must_change_password=False, role="subsidiary_rep", company=self.company
        )
        self.assertIn(medical, scoped_requests_for(head))
        self.assertNotIn(medical, scoped_requests_for(specialist))
        self.assertNotIn(medical, scoped_requests_for(rep))

        client = Client()
        client.force_login(head)
        self.assertEqual(client.get(reverse("request_detail", args=[medical.pk])).status_code, 200)
        decision = client.post(reverse("request_detail", args=[medical.pk]), {
            "status": ServiceRequest.Status.IN_REVIEW,
            "response": "در حال بررسی",
        })
        self.assertEqual(decision.status_code, 302)
        decision = client.post(reverse("request_detail", args=[medical.pk]), {
            "status": ServiceRequest.Status.APPROVED,
            "response": "درخواست بررسی و تأیید شد",
        })
        self.assertEqual(decision.status_code, 302)
        medical.refresh_from_db()
        self.assertEqual(medical.status, ServiceRequest.Status.APPROVED)
        client.force_login(specialist)
        self.assertEqual(client.get(reverse("request_detail", args=[medical.pk])).status_code, 404)

    def test_employee_cannot_change_request_status(self):
        item = ServiceRequest.objects.create(
            reference="IB-OWN-STATUS", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست من", description="شرح",
        )
        client = Client()
        client.force_login(self.user)
        for forbidden_status in (ServiceRequest.Status.APPROVED, ServiceRequest.Status.REJECTED, ServiceRequest.Status.COMPLETED):
            with self.subTest(status=forbidden_status):
                response = client.post(reverse("request_detail", args=[item.pk]), {
                    "status": forbidden_status, "response": "تصمیم نهایی"
                })
                self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.status, ServiceRequest.Status.SUBMITTED)

    def test_specialist_can_claim_unassigned_request_when_review_starts(self):
        item = ServiceRequest.objects.create(
            reference="IB-QUEUE-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست عادی", description="شرح",
        )
        specialist = User.objects.create_user(
            username="specialist-queue", password="StrongPass!2026",
            must_change_password=False, role="insurance_specialist"
        )
        client = Client()
        client.force_login(specialist)
        response = client.get(reverse("request_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "رسیدگی به درخواست")
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.IN_REVIEW, "response": "شروع بررسی"
        })
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.assigned_to_id, specialist.pk)
        self.assertEqual(item.status, ServiceRequest.Status.IN_REVIEW)
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.APPROVED, "response": "تأیید"
        })
        self.assertEqual(response.status_code, 403)

    def test_head_updates_do_not_claim_specialist_queue_and_response_history_is_preserved(self):
        item = ServiceRequest.objects.create(
            reference="IB-HISTORY-1", kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.user, company=self.company,
            title="درخواست تاریخچه", description="شرح",
        )
        head = User.objects.create_user(
            username="head-history", password="StrongPass!2026",
            must_change_password=False, role="department_head"
        )
        client = Client()
        client.force_login(head)
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.IN_REVIEW, "response": "بررسی آغاز شد"
        })
        self.assertEqual(response.status_code, 302)
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.NEEDS_INFO, "response": "لطفاً اطلاعات تکمیلی ارائه شود"
        })
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to_id)
        self.assertIn("بررسی آغاز شد", item.response)
        self.assertIn("لطفاً اطلاعات تکمیلی ارائه شود", item.response)

    def test_employee_medical_request_must_select_self_or_insured_dependent(self):
        self.user.national_id = "1111111111"
        self.user.save(update_fields=["national_id"])
        employee_person = Person.objects.create(
            company=self.company, national_id="1111111111",
            first_name="کارمند", last_name="آزمایشی",
        )
        dependent = Person.objects.create(
            company=self.company, national_id="2222222222",
            first_name="فرد", last_name="تحت تکفل",
            relationship="child", employee=employee_person,
        )
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            "person": str(dependent.pk),
            "title": "کمک‌هزینه درمان فرد تحت تکفل",
            "description": "درخواست آزمایشی",
        })
        self.assertEqual(response.status_code, 302)
        item = ServiceRequest.objects.get()
        self.assertEqual(item.person_id, dependent.pk)
        self.assertTrue(item.is_confidential)

    def test_employee_cannot_link_medical_request_to_person_from_another_company(self):
        self.user.national_id = "1111111111"
        self.user.save(update_fields=["national_id"])
        other_person = Person.objects.create(
            company=self.other_company, national_id="1111111111",
            first_name="شخص", last_name="شرکت دیگر",
        )
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            "person": str(other_person.pk),
            "title": "درخواست کمک‌هزینه",
            "description": "شرح",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServiceRequest.objects.count(), 0)

    def test_finance_and_auditor_cannot_open_request_creation_endpoint(self):
        for role in ("finance", "legal", "auditor", "insurer", "insurance_specialist"):
            with self.subTest(role=role):
                user = User.objects.create_user(
                    username=f"no-create-{role}", password="StrongPass!2026",
                    must_change_password=False, role=role,
                )
                client = Client()
                client.force_login(user)
                response = client.get(reverse("request_create"))
                self.assertEqual(response.status_code, 403)



class MedicalRequestConfidentialityInvariantTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="MED-CONF", name="شرکت محرمانه")
        self.user = User.objects.create_user(
            username="medical-conf-user",
            password="StrongPass!2026",
            role="employee",
            company=self.company,
            must_change_password=False,
        )

    def test_model_save_forces_medical_assistance_to_be_confidential(self):
        item = ServiceRequest.objects.create(
            reference="IB-MED-CONF-1",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.user,
            company=self.company,
            title="درخواست محرمانه",
            description="شرح آزمایشی",
            is_confidential=False,
        )

        self.assertTrue(item.is_confidential)
        item.refresh_from_db()
        self.assertTrue(item.is_confidential)

    def test_database_constraint_prevents_direct_declassification(self):
        from django.db import IntegrityError, transaction

        item = ServiceRequest.objects.create(
            reference="IB-MED-CONF-2",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.user,
            company=self.company,
            title="درخواست محرمانه دوم",
            description="شرح آزمایشی",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServiceRequest.objects.filter(pk=item.pk).update(is_confidential=False)
