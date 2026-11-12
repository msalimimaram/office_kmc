from datetime import date
from django.test import TestCase, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.models import RoleAssignment, User
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
from core.permissions import can_transition_request, scoped_requests_for
from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowStep, WorkflowTransition

NATIONAL_ID_A = "1" * 10
NATIONAL_ID_B = "2" * 10


class ServiceRequestTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="A", name="شرکت الف")
        self.other_company = Company.objects.create(code="B", name="شرکت ب")
        self.user = User.objects.create_user(
            username="emp", password="StrongPass!2026", must_change_password=False, role="employee", company=self.company
        )
        self.workflow_admin = User.objects.create_user(
            username="request-workflow-admin",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.workflow_admin,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            reason="مدیر سامانه برای تأیید گردش درخواست در آزمون",
        )

    def test_user_can_submit_request(self):
        representative = User.objects.create_user(
            username="request-initial-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="*",
            reason="نماینده اولیه کل شرکت برای آزمون درخواست با رشته نامشخص",
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.OTHER,
            title="گردش درخواست عمومی آزمون",
            created_by=self.workflow_admin,
        )
        initial = WorkflowStep.objects.create(
            definition=definition,
            code=ServiceRequest.Status.SUBMITTED,
            title="بررسی نماینده شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        WorkflowTransition.objects.create(
            definition=definition,
            source_step=initial,
            action_code="close-test-request",
            title="بستن آزمون",
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            closes_case=True,
        )
        definition.approved_by = self.workflow_admin
        definition.is_active = True
        definition.save()

        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": "other", "title": "درخواست آزمایشی", "description": "شرح آزمایشی"
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ServiceRequest.objects.count(), 1)
        self.assertEqual(ServiceRequest.objects.first().submitted_by, self.user)
        self.assertEqual(WorkflowCase.objects.count(), 1)
        self.assertEqual(WorkflowCase.objects.get().current_assignee_id, representative.pk)

    def test_only_representative_can_submit_own_request_and_receive_it(self):
        RoleAssignment.objects.create(
            user=self.user,
            role=RoleAssignment.Role.INSURED_PERSON,
            company=self.company,
            line_code="*",
            reason="Insured-person assignment for dual-role routing test",
        )
        RoleAssignment.objects.create(
            user=self.user,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="*",
            reason="Only company representative in own-request routing test",
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.OTHER,
            title="Workflow for requester who is also the sole representative",
            created_by=self.workflow_admin,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code=ServiceRequest.Status.SUBMITTED,
            title="Initial company representative review",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.approved_by = self.workflow_admin
        definition.is_active = True
        definition.save()

        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": ServiceRequest.Kind.OTHER,
            "title": "درخواست شخصی نماینده",
            "description": "درخواست‌دهنده تنها نماینده فعال شرکت است.",
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            RoleAssignment.objects.filter(
                role=RoleAssignment.Role.SUBSIDIARY_REP,
                company=self.company,
                is_active=True,
            ).count(),
            1,
        )
        item = ServiceRequest.objects.get(submitted_by=self.user)
        case = WorkflowCase.objects.get(object_id=str(item.pk))
        self.assertEqual(case.current_assignee_id, self.user.pk)
        self.assertEqual(item.assigned_to_id, self.user.pk)

    def test_missing_published_workflow_blocks_new_request_and_rolls_back(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(reverse("request_create"), {
            "kind": ServiceRequest.Kind.OTHER,
            "title": "درخواست بدون گردش منتشرشده",
            "description": "نباید بدون گردش ثبت شود",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "گردش‌کار فعال و منتشرشده")
        self.assertEqual(ServiceRequest.objects.count(), 0)
        self.assertEqual(WorkflowCase.objects.count(), 0)

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

    def test_employee_can_view_request_submitted_by_representative_for_linked_person(self):
        self.user.national_id = NATIONAL_ID_A
        self.user.save(update_fields=["national_id"])
        person = Person.objects.create(
            company=self.company,
            user=self.user,
            national_id=NATIONAL_ID_A,
            first_name="کارمند",
            last_name="آزمایشی",
            birth_date=date(1990, 1, 1),
        )
        representative = User.objects.create_user(
            username="request-on-behalf-rep",
            password="StrongPass!2026",
            must_change_password=False,
            role="subsidiary_rep",
            company=self.company,
        )
        item = ServiceRequest.objects.create(
            reference="IB-ON-BEHALF-001",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=representative,
            person=person,
            company=self.company,
            title="درخواست محرمانه ثبت‌شده توسط نماینده",
            description="درخواست به نمایندگی از بیمه‌شده ثبت شده است",
            is_confidential=True,
        )

        self.assertIn(item, scoped_requests_for(self.user))
        client = Client()
        client.force_login(self.user)
        response = client.get(reverse("request_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "درخواست محرمانه ثبت‌شده توسط نماینده")

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

    def test_specialist_can_process_only_explicitly_assigned_request(self):
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

        # There is no shared, unassigned specialist queue. A specialist must
        # receive an explicit assignment before the request becomes visible.
        response = client.get(reverse("request_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 404)

        item.assigned_to = specialist
        item.save(update_fields=["assigned_to", "updated_at"])
        response = client.get(reverse("request_detail", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "رسیدگی به درخواست")
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.IN_REVIEW, "response": "شروع بررسی"
        })
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.assigned_to_id, specialist.pk)
        self.assertEqual(item.status, ServiceRequest.Status.SUBMITTED)

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
        self.assertEqual(response.status_code, 403)
        response = client.post(reverse("request_detail", args=[item.pk]), {
            "status": ServiceRequest.Status.NEEDS_INFO, "response": "لطفاً اطلاعات تکمیلی ارائه شود"
        })
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to_id)
        self.assertEqual(item.status, ServiceRequest.Status.SUBMITTED)
        self.assertEqual(item.response, "")

    def test_employee_medical_request_must_select_self_or_insured_dependent(self):
        representative = User.objects.create_user(
            username="medical-initial-rep",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=self.company,
            line_code="health",
            reason="نماینده درمان شرکت",
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            title="گردش محرمانه کمک‌هزینه درمان",
            created_by=self.workflow_admin,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code=ServiceRequest.Status.SUBMITTED,
            title="دریافت اولیه نماینده شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.approved_by = self.workflow_admin
        definition.is_active = True
        definition.save()

        self.user.national_id = NATIONAL_ID_A
        self.user.save(update_fields=["national_id"])
        employee_person = Person.objects.create(
            company=self.company, national_id=NATIONAL_ID_A,
            first_name="کارمند", last_name="آزمایشی", birth_date=date(1990, 1, 1),
        )
        dependent = Person.objects.create(
            company=self.company, national_id=NATIONAL_ID_B,
            first_name="فرد", last_name="تحت تکفل", birth_date=date(2010, 1, 1),
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
        case = WorkflowCase.objects.get(object_id=str(item.pk))
        self.assertEqual(case.current_assignee_id, representative.pk)

    def test_employee_cannot_link_medical_request_to_person_from_another_company(self):
        self.user.national_id = NATIONAL_ID_A
        self.user.save(update_fields=["national_id"])
        other_person = Person.objects.create(
            company=self.other_company, national_id=NATIONAL_ID_B,
            first_name="شخص", last_name="شرکت دیگر", birth_date=date(1992, 1, 1),
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



class LegacyRequestTransitionPermissionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="TRANSITION", name="شرکت گردش کار")
        self.employee = User.objects.create_user(
            username="transition-employee",
            password="StrongPass!2026",
            role="employee",
            company=self.company,
            must_change_password=False,
        )
        self.specialist = User.objects.create_user(
            username="transition-specialist",
            password="StrongPass!2026",
            role="insurance_specialist",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=self.specialist,
            role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="*",
            reason="مجوز صریح تمام رشته‌ها برای درخواست فاقد رشته مشخص در آزمون سازگاری",
        )
        self.item = ServiceRequest.objects.create(
            reference="IB-TRANSITION-1",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.employee,
            company=self.company,
            assigned_to=self.specialist,
            title="درخواست گردش کار",
            description="شرح",
        )

    def test_assigned_specialist_can_start_review_but_cannot_make_decision(self):
        self.assertFalse(
            can_transition_request(
                self.specialist, self.item, ServiceRequest.Status.IN_REVIEW
            )
        )
        self.assertFalse(
            can_transition_request(
                self.specialist, self.item, ServiceRequest.Status.APPROVED
            )
        )
        self.assertFalse(
            can_transition_request(
                self.specialist, self.item, ServiceRequest.Status.REJECTED
            )
        )

    def test_requester_cannot_change_own_request_status(self):
        self.assertFalse(
            can_transition_request(
                self.employee, self.item, ServiceRequest.Status.IN_REVIEW
            )
        )

    def test_legacy_transition_graph_rejects_invalid_jump(self):
        self.assertFalse(
            can_transition_request(
                self.specialist, self.item, ServiceRequest.Status.CLOSED
            )
        )



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



class ServiceRequestAttachmentDownloadTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="ATT-A", name="شرکت پیوست")
        self.other_company = Company.objects.create(code="ATT-B", name="شرکت دیگر پیوست")
        self.owner = User.objects.create_user(
            username="attachment-owner",
            password="StrongPass!2026",
            must_change_password=False,
            role="employee",
            company=self.company,
        )
        self.other_owner = User.objects.create_user(
            username="attachment-other",
            password="StrongPass!2026",
            must_change_password=False,
            role="employee",
            company=self.other_company,
        )
        self.item = ServiceRequest.objects.create(
            reference="IB-ATTACHMENT-1",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.owner,
            company=self.company,
            title="درخواست دارای پیوست",
            description="شرح درخواست",
            attachment=SimpleUploadedFile(
                "supporting-document.pdf",
                b"%PDF-1.4 test attachment",
                content_type="application/pdf",
            ),
        )

    def test_owner_can_download_request_attachment_and_download_is_audited(self):
        from auditlog.models import AuditEvent

        client = Client()
        client.force_login(self.owner)
        detail = client.get(reverse("request_detail", args=[self.item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, reverse("request_attachment_download", args=[self.item.pk]))

        response = client.get(reverse("request_attachment_download", args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get("Content-Disposition", "").split(";")[0], "attachment")
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 test attachment")
        self.assertTrue(
            AuditEvent.objects.filter(
                actor=self.owner,
                action="service_request_attachment_downloaded",
                object_id=str(self.item.pk),
            ).exists()
        )

    def test_attachment_download_is_denied_outside_request_visibility_scope(self):
        client = Client()
        client.force_login(self.other_owner)
        response = client.get(reverse("request_attachment_download", args=[self.item.pk]))
        self.assertEqual(response.status_code, 404)

        unauthenticated = Client()
        response = unauthenticated.get(reverse("request_attachment_download", args=[self.item.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_confidential_attachment_requires_global_access(self):
        item = ServiceRequest.objects.create(
            reference="IB-PRIVATE-ATTACHMENT",
            kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=self.owner,
            company=self.company,
            title="درخواست محرمانه",
            description="شرح",
            attachment=SimpleUploadedFile("restricted.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
        )
        self.addCleanup(item.attachment.delete, save=False)
        client = Client()
        client.force_login(self.owner)
        detail = client.get(reverse("request_detail", args=[item.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, reverse("request_attachment_download", args=[item.pk]))
        self.assertEqual(client.get(reverse("request_attachment_download", args=[item.pk])).status_code, 403)

        head = User.objects.create_user(username="private-attachment-head", password="StrongPass!2026", role="department_head", must_change_password=False)
        client.force_login(head)
        response = client.get(reverse("request_attachment_download", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        # Close the streaming file before TestCase cleanup removes it (Windows locks open files).
        response.close()

    def test_attachment_download_returns_404_when_request_has_no_file(self):
        item_without_file = ServiceRequest.objects.create(
            reference="IB-ATTACHMENT-2",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.owner,
            company=self.company,
            title="درخواست بدون پیوست",
            description="شرح درخواست",
        )
        client = Client()
        client.force_login(self.owner)
        response = client.get(reverse("request_attachment_download", args=[item_without_file.pk]))
        self.assertEqual(response.status_code, 404)



class ServiceRequestAdminIsolationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(code="ADM-REQ", name="شرکت آزمون ادمین")
        self.admin = User.objects.create_user(
            username="request-admin",
            password="StrongPass!2026",
            role="system_admin",
            is_staff=True,
            must_change_password=False,
        )
        self.item = ServiceRequest.objects.create(
            reference="IB-ADM-001",
            kind=ServiceRequest.Kind.OTHER,
            submitted_by=self.admin,
            company=self.company,
            title="درخواست فقط‌خواندنی",
            description="آزمون جلوگیری از دور زدن گردش کار",
            status=ServiceRequest.Status.SUBMITTED,
        )
        self.client.force_login(self.admin)

    def test_global_operator_can_view_requests_but_cannot_add_change_or_delete(self):
        changelist = reverse("admin:requests_portal_servicerequest_changelist")
        detail = reverse("admin:requests_portal_servicerequest_change", args=[self.item.pk])
        add = reverse("admin:requests_portal_servicerequest_add")
        delete = reverse("admin:requests_portal_servicerequest_delete", args=[self.item.pk])

        self.assertEqual(self.client.get(changelist).status_code, 200)
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.assertEqual(self.client.get(add).status_code, 403)
        self.assertEqual(self.client.get(delete).status_code, 403)

    def test_admin_post_cannot_change_request_status_or_assignment(self):
        detail = reverse("admin:requests_portal_servicerequest_change", args=[self.item.pk])
        response = self.client.post(detail, {
            "status": ServiceRequest.Status.CLOSED,
            "assigned_to": "",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ServiceRequest.Status.SUBMITTED)
        self.assertIsNone(self.item.assigned_to_id)


class RequestWorkflowConfigurationFailureTests(TestCase):
    def test_missing_initial_recipient_returns_form_error_and_rolls_back_request(self):
        company = Company.objects.create(code="WF-EMPTY", name="شرکت بدون گیرنده")
        submitter = User.objects.create_user(
            username="wf-submit",
            password="StrongPass!2026",
            role="employee",
            company=company,
            must_change_password=False,
        )
        administrator = User.objects.create_user(
            username="wf-admin",
            password="StrongPass!2026",
            role="system_admin",
            is_staff=True,
            must_change_password=False,
        )
        definition = WorkflowDefinition.objects.create(
            code=ServiceRequest.Kind.OTHER,
            title="گردش آزمایشی بدون گیرنده",
            created_by=administrator,
            approved_by=administrator,
            is_active=False,
        )
        WorkflowStep.objects.create(
            definition=definition,
            code="company-review",
            title="بررسی نماینده شرکت",
            order=1,
            allowed_roles=[RoleAssignment.Role.SUBSIDIARY_REP],
            is_initial=True,
        )
        definition.is_active = True
        definition.save()

        client = Client()
        client.force_login(submitter)
        response = client.post(reverse("request_create"), {
            "kind": ServiceRequest.Kind.OTHER,
            "title": "درخواست با تعریف ناقص",
            "description": "این ثبت باید به‌صورت کنترل‌شده رد شود.",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "گیرنده‌ای با انتصاب معتبر")
        self.assertEqual(ServiceRequest.objects.filter(submitted_by=submitter).count(), 0)
        self.assertEqual(WorkflowCase.objects.count(), 0)


class LegacyIdentityRequestRouteTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            code="REQ-LEGACY-IDENTITY",
            name="شرکت مسیر اصلاح اطلاعات",
        )
        self.employee = User.objects.create_user(
            username="legacy-identity-employee",
            password="StrongPass!2026",
            role="employee",
            company=self.company,
            must_change_password=False,
        )

    def test_generic_request_form_does_not_offer_identity_or_iban_changes(self):
        from requests_portal.forms import ServiceRequestForm

        form = ServiceRequestForm(user=self.employee)
        choices = {value for value, _label in form.fields["kind"].choices}
        self.assertNotIn(ServiceRequest.Kind.IDENTITY_CHANGE, choices)
        self.assertNotIn(ServiceRequest.Kind.IBAN_CHANGE, choices)

    def test_legacy_identity_and_iban_posts_are_rejected_without_creating_requests(self):
        client = Client()
        client.force_login(self.employee)
        for kind in (
            ServiceRequest.Kind.IDENTITY_CHANGE,
            ServiceRequest.Kind.IBAN_CHANGE,
        ):
            with self.subTest(kind=kind):
                response = client.post(reverse("request_create"), {
                    "kind": kind,
                    "title": "اصلاح اطلاعات",
                    "description": "این مسیر قدیمی نباید درخواست جدید بسازد.",
                })
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "مسیر مستقل")
        self.assertEqual(ServiceRequest.objects.count(), 0)
        self.assertEqual(WorkflowCase.objects.count(), 0)
