from django.test import TestCase

from accounts.models import RoleAssignment, User
from core.permissions import can_edit_iban, scoped_requests_for
from organizations.models import Company
from requests_portal.models import ServiceRequest
from workflow.models import WorkflowCase, WorkflowDefinition, WorkflowStep


class ConfidentialRequestScopeTests(TestCase):
    def test_legacy_assigned_to_does_not_grant_confidential_request_access(self):
        company = Company.objects.create(code="SCOPE-A", name="شرکت آزمایشی")
        employee = User.objects.create_user(
            username="scope-employee", password="StrongPass!2026",
            role="employee", company=company, must_change_password=False,
        )
        specialist = User.objects.create_user(
            username="scope-specialist", password="StrongPass!2026",
            role="insurance_specialist", must_change_password=False,
        )
        item = ServiceRequest.objects.create(
            reference="IB-LEGACY-SECRET", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=employee, company=company, assigned_to=specialist,
            title="محرمانه", description="شرح محرمانه", is_confidential=True,
        )
        self.assertNotIn(item, scoped_requests_for(specialist))

    def test_only_current_health_workflow_assignee_gets_confidential_metadata_scope(self):
        company = Company.objects.create(code="SCOPE-B", name="شرکت ب")
        employee = User.objects.create_user(
            username="scope-employee-b", password="StrongPass!2026",
            role="employee", company=company, must_change_password=False,
        )
        specialist = User.objects.create_user(
            username="scope-specialist-b", password="StrongPass!2026",
            role="insurance_specialist", must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=specialist, role=RoleAssignment.Role.INSURANCE_SPECIALIST,
            line_code="health", reason="ارجاع صریح پرونده درمان",
        )
        item = ServiceRequest.objects.create(
            reference="IB-WF-SECRET", kind=ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            submitted_by=employee, company=company,
            title="عنوان پزشکی محرمانه", description="شرح پزشکی محرمانه",
            is_confidential=True,
        )
        approver = User.objects.create_user(
            username="scope-workflow-approver",
            password="StrongPass!2026",
            must_change_password=False,
        )
        RoleAssignment.objects.create(
            user=approver,
            role=RoleAssignment.Role.DEPARTMENT_HEAD,
            reason="تأیید گردش کار در آزمون محدوده محرمانه",
        )
        definition = WorkflowDefinition.objects.create(
            code="scope-medical", title="گردش محرمانه", created_by=approver,
        )
        step = WorkflowStep.objects.create(
            definition=definition, code="review", title="بررسی درمان", order=1,
            allowed_roles=[RoleAssignment.Role.INSURANCE_SPECIALIST], is_initial=True,
        )
        definition.approved_by = approver
        definition.is_active = True
        definition.save()
        from django.contrib.contenttypes.models import ContentType
        case = WorkflowCase.objects.create(
            definition=definition,
            content_type=ContentType.objects.get_for_model(item, for_concrete_model=False),
            object_id=str(item.pk), current_step=step, current_assignee=specialist,
        )
        self.assertIn(item, scoped_requests_for(specialist))
        case.current_assignee = employee
        case.save(update_fields=["current_assignee"])
        self.assertNotIn(item, scoped_requests_for(specialist))


class SensitivePersonFieldPermissionTests(TestCase):
    def test_direct_iban_edit_is_denied_even_for_privileged_users(self):
        admin = User.objects.create_user(
            username="iban-workflow-admin",
            password="StrongPass!2026",
            is_superuser=True,
            is_staff=True,
        )
        specialist = User.objects.create_user(
            username="iban-workflow-specialist",
            password="StrongPass!2026",
            role="insurance_specialist",
        )
        self.assertFalse(can_edit_iban(admin, None))
        self.assertFalse(can_edit_iban(specialist, None))
