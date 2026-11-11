"""Comprehensive, idempotent demo fixtures for the complete insurance workflow domain.

All records are synthetic and namespaced. Existing rows are verified, never
silently updated or deleted. This module is called by seed_demo in DEBUG only.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
import secrets
import os

import jdatetime
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook

from accounts.models import (
    OrganizationalPosition, OrganizationalUnit, PositionAssignment,
    RoleAssignment, User, UserNotification,
)
from announcements.models import Announcement
from assets.models import (
    AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation,
    InsuredAsset, Vehicle,
)
from auditlog.models import AuditEvent
from claims.models import Claim, ClaimObjection, ClaimPayment
from correspondence.models import (
    Correspondence, CorrespondenceEvent, CorrespondenceLink, CorrespondenceSequence,
)
from delegations.models import DelegationEvent, WorkDelegation
from documents.models import DocumentAccessEvent, DocumentLink, DocumentRecord, DocumentVersion
from imports.models import ImportBatch
from insurance.models import Contract, ContractRevision, InsuranceLine, Insurer
from organizations.models import (
    Company, CompanyLeadershipTitle, Person, PersonChangeRequest, PersonEmployment,
)
from requests_portal.models import ServiceRequest
from tasks.models import InternalTask, TaskEvent
from workflow.models import (
    BusinessCalendar, CalendarHoliday, WorkflowCase, WorkflowDefinition,
    WorkflowEvent, WorkflowStep, WorkflowTransition,
)
from workflow.services import resolve_initial_assignee, start_workflow, transition_case


EXPECTED_MODEL_LABELS = (
    "accounts.user", "accounts.organizationalunit", "accounts.organizationalposition",
    "accounts.roleassignment", "accounts.positionassignment", "accounts.usernotification",
    "announcements.announcement",
    "assets.insuredasset", "assets.vehicle", "assets.assetvaluation",
    "assets.assetpolicyperiod", "assets.assetpolicyendorsement",
    "auditlog.auditevent",
    "claims.claim", "claims.claimpayment", "claims.claimobjection",
    "correspondence.correspondencesequence", "correspondence.correspondence",
    "correspondence.correspondencelink", "correspondence.correspondenceevent",
    "delegations.workdelegation", "delegations.delegationevent",
    "documents.documentrecord", "documents.documentversion",
    "documents.documentlink", "documents.documentaccessevent",
    "imports.importbatch",
    "insurance.insurer", "insurance.contract", "insurance.contractrevision",
    "organizations.company", "organizations.person", "organizations.personemployment",
    "organizations.companyleadershiptitle", "organizations.personchangerequest",
    "requests_portal.servicerequest",
    "tasks.internaltask", "tasks.taskevent",
    "workflow.workflowdefinition", "workflow.workflowstep", "workflow.workflowtransition",
    "workflow.workflowcase", "workflow.workflowevent", "workflow.businesscalendar",
    "workflow.calendarholiday",
)


def _content(name, body):
    return ContentFile(body, name=name)


def _sample_xlsx(name, headers, row):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Demo"
    sheet.append(headers)
    sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return _content(name, buffer.getvalue())


def _ensure_workflow(obj, code, actor, assignee, note="داده نمونه برای آزمون گردش کار"):
    from workflow.services import start_workflow

    definition = WorkflowDefinition.objects.filter(code=code, is_active=True).order_by("-version").first()
    if not definition:
        raise CommandError(f"گردش‌کار فعال {code} یافت نشد؛ seed_operational_workflows باید اجرا شود.")
    content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
    case = WorkflowCase.objects.filter(
        definition=definition, content_type=content_type, object_id=str(obj.pk)
    ).first()
    if case:
        return case, False
    resolved_assignee, delegation = resolve_initial_assignee(
        definition=definition,
        obj=obj,
        return_delegation=True,
    )
    target_assignee = delegation.delegate_to if delegation is not None else resolved_assignee
    return start_workflow(
        obj=obj,
        code=code,
        actor=actor,
        assignee=target_assignee,
        delegation=delegation,
        note=note,
    ), True


@transaction.atomic
def seed_extended_fixtures(*, record, users, company_a, company_b, insurer, employee_a, employee_b, created_counts=None, reused_counts=None):
    """Create 150+ interconnected demo records across all 45 domain models."""
    from core.management.commands.seed_operational_workflows import Command as WorkflowSeedCommand
    WorkflowSeedCommand().handle()

    today = timezone.localdate()
    now = timezone.now()
    start_date = date(2026, 1, 1)
    end_date = date(2028, 12, 29)
    admin = users["admin.demo"]
    head = users["head.demo"]
    specialist = users["specialist.demo"]
    company_rep_a = users["companya.demo"]
    company_rep_b = users["companyb.demo"]
    insurer_rep = users["insurer.demo"]

    def ensure(model, lookup, defaults, verify_fields=None):
        return record(model, lookup, defaults, verify_fields)[0]

    additional_users_created = []

    def demo_user(username, role, *, company=None, national_id="", insurer_obj=None):
        defaults = {
            "role": role,
            "company": company,
            "national_id": national_id,
            "insurer": insurer_obj,
            "is_active": True,
            "must_change_password": False,
        }
        user = User.objects.filter(username=username).first()
        if user:
            if reused_counts is not None:
                reused_counts[User._meta.label] = reused_counts.get(User._meta.label, 0) + 1
            for field, value in defaults.items():
                if field == "must_change_password":
                    continue
                if getattr(user, field) != value:
                    raise CommandError(
                        f"Seed collision in User ({username}): {field} differs; account untouched."
                    )
            if not user.has_usable_password():
                demo_password = os.environ.get("PRESENTATION_DEMO_PASSWORD", "")
                if not demo_password:
                    raise CommandError("PRESENTATION_DEMO_PASSWORD is required for demo accounts.")
                user.set_password(demo_password)
                user.must_change_password = False
                user.save(update_fields=["password", "must_change_password"])
            return user
        demo_password = os.environ.get("PRESENTATION_DEMO_PASSWORD", "")
        if not demo_password:
            raise CommandError("PRESENTATION_DEMO_PASSWORD is required for demo accounts.")
        user = User(username=username, **defaults)
        user.set_password(demo_password)
        user.save()
        if created_counts is not None:
            created_counts[User._meta.label] = created_counts.get(User._meta.label, 0) + 1
        additional_users_created.append(username)
        return user

    # Additional company and insurer scopes allow cross-company and cross-insurer tests.
    company_c = ensure(
        Company, {"code": "DEMO-C"},
        {"name": "شرکت نمونه ج", "parent": company_a, "is_parent": False, "is_active": True},
        verify_fields=(),
    )
    company_d = ensure(
        Company, {"code": "DEMO-D"},
        {"name": "شرکت نمونه د", "parent": company_a, "is_parent": False, "is_active": True},
        verify_fields=(),
    )
    insurer_b = ensure(
        Insurer, {"name": "بیمه‌گر نمونه دوم"},
        {"contact_name": "کارشناس نمونه دوم", "contact_email": "demo.insurer2@example.invalid",
         "contact_phone": "02100000002", "is_active": True},
        verify_fields=(),
    )

    fire_specialist = users["Delbari"]
    second_insurer_user = demo_user(
        "Saman2", User.Role.INSURER, insurer_obj=insurer_b
    )
    company_c_rep = demo_user(
        "Namayande3", User.Role.SUBSIDIARY_REP, company=company_c
    )
    company_d_rep = demo_user(
        "Namayande4", User.Role.SUBSIDIARY_REP, company=company_d
    )
    users.update({
        "specialist.fire.demo": fire_specialist,
        "insurer.two.demo": second_insurer_user,
        "companyc.demo": company_c_rep,
        "companyd.demo": company_d_rep,
    })
    extra_users = {
        "Delbari": fire_specialist,
        "Saman2": second_insurer_user,
        "Namayande3": company_c_rep,
        "Namayande4": company_d_rep,
    }

    assignment_specs = (
        (fire_specialist, RoleAssignment.Role.INSURANCE_SPECIALIST, None, None, "fire"),
        (second_insurer_user, RoleAssignment.Role.INSURER_REP, None, insurer_b, ""),
        (company_c_rep, RoleAssignment.Role.SUBSIDIARY_REP, company_c, None, "*"),
        (company_d_rep, RoleAssignment.Role.SUBSIDIARY_REP, company_d, None, "*"),
    )
    for user, role, company, insurer_obj, line_code in assignment_specs:
        ensure(
            RoleAssignment,
            {"user": user, "role": role, "company": company, "insurer": insurer_obj, "line_code": line_code},
            {
                "valid_from": start_date, "valid_until": None, "is_active": True,
                "reason": "انتصاب تکمیلی داده نمونه",
                "granted_by": admin, "approved_by": head,
            },
            verify_fields=(),
        )

    # Contracts cover every insurance line and are linked to realistic company groups.
    line_contracts = {InsuranceLine.HEALTH: Contract.objects.get(code="DEMO-1405")}
    contract_specs = (
        ("DEMO-LIFE-01", "قرارداد نمونه عمر و حوادث", insurer, InsuranceLine.LIFE, [company_a, company_b, company_c]),
        ("DEMO-LIABILITY-01", "قرارداد نمونه مسئولیت", insurer_b, InsuranceLine.LIABILITY, [company_a, company_d]),
        ("DEMO-FIRE-01", "قرارداد نمونه آتش‌سوزی", insurer_b, InsuranceLine.FIRE, [company_a, company_b, company_c, company_d]),
        ("DEMO-TP-01", "قرارداد نمونه شخص ثالث", insurer, InsuranceLine.THIRD_PARTY, [company_a, company_b, company_c, company_d]),
        ("DEMO-BODY-01", "قرارداد نمونه بدنه خودرو", insurer_b, InsuranceLine.BODY, [company_a, company_b, company_c]),
        ("DEMO-OTHER-01", "قرارداد نمونه سایر پوشش‌ها", insurer, InsuranceLine.OTHER, [company_b, company_c, company_d]),
    )
    for code, title, contract_insurer, line, companies in contract_specs:
        contract, created = record(
            Contract,
            {"code": code},
            {
                "title": title, "insurer": contract_insurer, "line": line,
                "start_date": start_date, "end_date": end_date,
                "coverage_summary": f"پوشش آزمایشی رشته {line}",
                "terms": "شرایط و استثناهای ساختگی؛ فاقد اثر حقوقی.",
                "status": Contract.Status.ACTIVE, "is_active": True,
            },
            verify_fields=(),
        )
        if created:
            contract.companies.set(companies)
        line_contracts[line] = contract

    # A small but diverse synthetic workforce with historical and current employment.
    people_specs = (
        ("0012345680", company_a, "مریم", "آزمایشی", "A-1002", Person.Relationship.EMPLOYEE, None, date(1992, 4, 3)),
        ("0012345681", company_b, "حسین", "آزمایشی", "B-2002", Person.Relationship.EMPLOYEE, None, date(1989, 7, 17)),
        ("0012345682", company_c, "نازنین", "آزمایشی", "C-3001", Person.Relationship.EMPLOYEE, None, date(1994, 2, 9)),
        ("0012345683", company_d, "امیر", "آزمایشی", "D-4001", Person.Relationship.EMPLOYEE, None, date(1986, 11, 28)),
        ("0012345684", company_b, "نیلوفر", "آزمایشی", "B-2001-01", Person.Relationship.CHILD, employee_b, date(2015, 6, 1)),
        ("0012345685", company_c, "رها", "آزمایشی", "C-3001-01", Person.Relationship.SPOUSE, None, date(1996, 8, 12)),
        ("0012345686", company_d, "سامان", "آزمایشی", "D-4001-01", Person.Relationship.CHILD, None, date(2014, 10, 4)),
    )
    people = [employee_a, employee_b]
    for national_id, company, first, last, code, relationship, employee, birth_date in people_specs:
        person = ensure(
            Person, {"national_id": national_id},
            {
                "company": company, "personnel_code": code, "first_name": first,
                "last_name": last, "birth_date": birth_date, "relationship": relationship,
                "employee": employee, "is_insured": True, "is_active": True,
            },
            verify_fields=(),
        )
        people.append(person)

    primary_people = [employee_a, employee_b] + [
        Person.objects.get(national_id=item[0]) for item in people_specs[:4]
    ]
    for person in primary_people:
        company = person.company
        ensure(
            PersonEmployment,
            {"person": person, "company": company},
            {
                "personnel_code": person.personnel_code,
                "job_title": "کارمند نمونه",
                "valid_from": start_date,
                "valid_until": None,
                "status": PersonEmployment.Status.ACTIVE,
                "source_reference": "DEMO-SEED",
                "created_by": head,
                "approved_by": head,
            },
            verify_fields=(),
        )
    # Dependent records use a valid parent and are kept separate from employment history.
    dependent_b = Person.objects.get(national_id="0012345684")
    if dependent_b.employee_id != employee_b.pk:
        raise CommandError("Seed collision: dependent DEMO person 0012345684 has a different primary insured.")
    dependent_c = Person.objects.get(national_id="0012345685")
    parent_c = Person.objects.get(national_id="0012345682")
    if dependent_c.employee_id is None:
        dependent_c.employee = parent_c
        dependent_c.save(update_fields=["employee"])
    elif dependent_c.employee_id != parent_c.pk:
        raise CommandError("Seed collision: dependent DEMO person 0012345685 has a different primary insured.")
    dependent_d = Person.objects.get(national_id="0012345686")
    parent_d = Person.objects.get(national_id="0012345683")
    if dependent_d.employee_id is None:
        dependent_d.employee = parent_d
        dependent_d.save(update_fields=["employee"])
    elif dependent_d.employee_id != parent_d.pk:
        raise CommandError("Seed collision: dependent DEMO person 0012345686 has a different primary insured.")

    # Internal organizational chart and multiple position assignments.
    unit_hq = ensure(
        OrganizationalUnit, {"code": "DEMO-HQ"},
        {"name": "اداره مرکزی بیمه نمونه", "parent": None, "company": None, "is_active": True},
    )
    unit_health = ensure(
        OrganizationalUnit, {"code": "DEMO-HEALTH"},
        {"name": "واحد کارشناسی درمان", "parent": unit_hq, "company": None, "is_active": True},
    )
    unit_property = ensure(
        OrganizationalUnit, {"code": "DEMO-PROPERTY"},
        {"name": "واحد اموال و مسئولیت", "parent": unit_hq, "company": None, "is_active": True},
    )
    position_specs = (
        (unit_hq, "DEMO-HEAD", "رئیس اداره بیمه", OrganizationalPosition.Level.HEAD),
        (unit_health, "DEMO-HEALTH-EXPERT", "کارشناس درمان", OrganizationalPosition.Level.SPECIALIST),
        (unit_property, "DEMO-FIRE-EXPERT", "کارشناس آتش‌سوزی", OrganizationalPosition.Level.SPECIALIST),
        (unit_hq, "DEMO-SUPERVISOR", "سرپرست عملیات", OrganizationalPosition.Level.SUPERVISOR),
    )
    positions = {}
    for unit, code, title, level in position_specs:
        positions[code] = ensure(
            OrganizationalPosition, {"unit": unit, "code": code},
            {"title": title, "level": level, "is_active": True},
        )
    for user, unit, code in (
        (head, unit_hq, "DEMO-HEAD"),
        (specialist, unit_health, "DEMO-HEALTH-EXPERT"),
        (fire_specialist, unit_property, "DEMO-FIRE-EXPERT"),
        (users["admin.demo"], unit_hq, "DEMO-SUPERVISOR"),
    ):
        position = positions[code]
        ensure(
            PositionAssignment,
            {"user": user, "unit": unit, "position": position, "line_code": ""},
            {
                "valid_from": start_date, "valid_until": None, "is_active": True,
                "reason": "سمت سازمانی نمونه", "granted_by": admin, "approved_by": head,
            },
            verify_fields=("reason", "granted_by", "approved_by"),
        )

    for company, person, title, declarer in (
        (company_a, employee_a, "مدیر منابع انسانی", company_rep_a),
        (company_a, employee_a, "نماینده سلامت و درمان", company_rep_a),
        (company_b, employee_b, "مدیر پشتیبانی", company_rep_b),
        (company_c, Person.objects.get(national_id="0012345682"), "نماینده شرکت", company_c_rep),
        (company_d, Person.objects.get(national_id="0012345683"), "مدیر عملیات", company_d_rep),
    ):
        ensure(
            CompanyLeadershipTitle,
            {"company": company, "person": person, "title": title},
            {"valid_from": start_date, "valid_until": None, "declared_by": declarer},
            verify_fields=(),
        )

    # All service-request kinds, including confidential and administrative variants.
    request_people = {
        company_a.pk: (employee_a, users["employee.a"], company_rep_a),
        company_b.pk: (employee_b, users["employee.b"], company_rep_b),
        company_c.pk: (Person.objects.get(national_id="0012345682"), company_c_rep, company_c_rep),
        company_d.pk: (Person.objects.get(national_id="0012345683"), company_d_rep, company_d_rep),
    }
    service_requests = list(ServiceRequest.objects.filter(reference__in=["IB-DEMO-001", "IB-DEMO-002"]))
    request_workflows = {}
    for index, (kind, label) in enumerate(ServiceRequest.Kind.choices, start=1):
        company = (company_a, company_b, company_c, company_d)[(index - 1) % 4]
        person, submitter, representative = request_people[company.pk]
        item, _ = record(
            ServiceRequest,
            {"reference": f"DEMO-REQ-{index:03d}"},
            {
                "kind": kind,
                "submitted_by": submitter,
                "person": person,
                "company": company,
                "title": f"درخواست آزمایشی {label}",
                "description": f"سناریوی نمونه برای آزمون فرآیند {label}؛ فاقد اثر واقعی.",
                "status": ServiceRequest.Status.SUBMITTED,
                "assigned_to": None,
                "is_confidential": kind == ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            },
            verify_fields=(),
        )
        service_requests.append(item)
        case, case_created = _ensure_workflow(
            item, kind, submitter, representative,
            note=f"شروع گردش کار سناریوی {kind}",
        )
        request_workflows[item.reference] = (case, case_created)

    # Exercise several independent operational paths once. Existing cases are never
    # replayed or rewound on a subsequent seed run.
    def advance_demo_request(reference, action_code, actor, recipient=None, note="اقدام نمونه برای آزمون گردش کار"):
        case, was_created = request_workflows[reference]
        if not was_created:
            return case
        return transition_case(
            case_id=case.pk,
            actor=actor,
            action_code=action_code,
            recipient=recipient,
            note=note,
        )

    # Waiting for employee information.
    advance_demo_request("DEMO-REQ-001", "accept_for_review", company_rep_a, head)
    advance_demo_request(
        "DEMO-REQ-001", "request_information", head, users["employee.a"],
        note="برای تکمیل بررسی، مدرک تکمیلی نمونه ارسال شود.",
    )
    # Internal review and insurer referral.
    advance_demo_request("DEMO-REQ-005", "accept_for_review", company_rep_a, head)
    advance_demo_request(
        "DEMO-REQ-005", "refer_to_insurer", head, insurer_rep,
        note="برای بررسی پوشش و اعلام نتیجه به بیمه‌گر ارجاع شد.",
    )
    # Approved request, still awaiting completion.
    advance_demo_request("DEMO-REQ-006", "accept_for_review", company_rep_b, head)
    advance_demo_request("DEMO-REQ-006", "approve", head, head)
    # Rejected request, kept in its rejected state for review.
    advance_demo_request("DEMO-REQ-007", "accept_for_review", company_c_rep, head)
    advance_demo_request(
        "DEMO-REQ-007", "reject", head, admin,
        note="درخواست نمونه با توجه به شرایط قرارداد قابل تأیید نیست.",
    )
    # Completed but not finally closed.
    advance_demo_request("DEMO-REQ-009", "accept_for_review", company_rep_a, head)
    advance_demo_request("DEMO-REQ-009", "approve", head, head)
    advance_demo_request("DEMO-REQ-009", "mark_completed", head, admin)
    # Fully closed request.
    advance_demo_request("DEMO-REQ-010", "accept_for_review", company_rep_b, head)
    advance_demo_request("DEMO-REQ-010", "approve", head, head)
    advance_demo_request("DEMO-REQ-010", "mark_completed", head, admin)
    advance_demo_request("DEMO-REQ-010", "finalize_completion", admin, None)

    # Person-change flows are created as immutable requests, never by overwriting Person fields.
    person_change_requests = []
    for index, (person, company, requester, representative, change_type, requested_value) in enumerate((
        (employee_a, company_a, users["employee.a"], company_rep_a, PersonChangeRequest.ChangeType.MOBILE, "09121111111"),
        (employee_a, company_a, users["employee.a"], company_rep_a, PersonChangeRequest.ChangeType.IBAN, "IR" + "1" * 24),
        (employee_b, company_b, users["employee.b"], company_rep_b, PersonChangeRequest.ChangeType.MOBILE, "09122222222"),
    ), start=1):
        current = getattr(person, PersonChangeRequest.FIELD_MAP[change_type])
        current_value = current.isoformat() if hasattr(current, "isoformat") else str(current or "")
        change, _ = record(
            PersonChangeRequest,
            {"person": person, "change_type": change_type},
            {
                "company": company,
                "contract": line_contracts[InsuranceLine.HEALTH],
                "requested_by": requester,
                "current_value": current_value,
                "requested_value": requested_value,
                "reason": f"درخواست آزمایشی اصلاح اطلاعات شماره {index}؛ بررسی و تأیید مستقل لازم است.",
                "status": PersonChangeRequest.Status.SUBMITTED,
            },
            verify_fields=("company", "contract", "requested_by", "requested_value", "reason"),
        )
        person_change_requests.append(change)
        _ensure_workflow(
            change, "person_change", requester, representative,
            note="ارجاع نمونه به نماینده شرکت",
        )

    # Claim-state coverage with coherent dates, amounts, source references and duplicate declarations.
    claim_statuses = (
        Claim.Status.REGISTERED, Claim.Status.UNDER_REVIEW, Claim.Status.NEEDS_INFO,
        Claim.Status.PENDING_DECISION, Claim.Status.APPROVED, Claim.Status.REJECTED,
        Claim.Status.PARTIALLY_PAID, Claim.Status.PAID, Claim.Status.CLOSED,
    )
    seeded_claims = []
    for index, status in enumerate(claim_statuses, start=1):
        company = company_a if index % 2 else company_b
        person = employee_a if index % 2 else employee_b
        contract = line_contracts[InsuranceLine.HEALTH]
        payable = Decimal("600000")
        paid = Decimal("0")
        if status == Claim.Status.PARTIALLY_PAID:
            paid = Decimal("250000")
        elif status in {Claim.Status.PAID, Claim.Status.CLOSED}:
            paid = payable
        assessed = Decimal("700000") if status not in {Claim.Status.REGISTERED, Claim.Status.NEEDS_INFO} else Decimal("0")
        duplicate = index == 9
        claim, _ = record(
            Claim,
            {"claim_number": f"DEMO-FULL-CLM-{index:03d}"},
            {
                "source_claim_number": f"INS-SAMPLE-{index:03d}",
                "person": person,
                "company_snapshot": company,
                "contract": contract,
                "insurer": insurer,
                "service_date": today - timedelta(days=index + 5),
                "registered_date": today - timedelta(days=index),
                "source_registered_date": today - timedelta(days=index),
                "contract_number_snapshot": contract.code,
                "service_type": ("نمونه خسارت تکراری اعلام‌شده" if duplicate else "خدمت درمانی نمونه"),
                "requested_amount": Decimal("900000"),
                "assessed_amount": assessed,
                "payable_amount": payable if status != Claim.Status.REJECTED else Decimal("0"),
                "paid_amount": Decimal("200000") if status == Claim.Status.PARTIALLY_PAID else paid,
                "payment_date": today - timedelta(days=1) if paid else None,
                "status": status,
                "source_reference": "DEMO-SEED",
                "source_duplicate_status": Claim.DuplicateStatus.DECLARED_DUPLICATE if duplicate else Claim.DuplicateStatus.NOT_DECLARED,
                "source_duplicate_reference": "INS-SAMPLE-001" if duplicate else "",
                "source_duplicate_note": "تکراری بودن فقط توسط نماینده بیمه‌گر اعلام شده است." if duplicate else "",
                "source_duplicate_reported_at": now if duplicate else None,
                "source_duplicate_reported_by": insurer_rep if duplicate else None,
                "assessment_note": "ارزیابی غیرپزشکی نمونه" if assessed else "",
                "assessed_by": specialist if assessed else None,
                "assessed_at": now - timedelta(days=1) if assessed else None,
                "result_sent_at": now - timedelta(days=2) if status in {Claim.Status.APPROVED, Claim.Status.REJECTED, Claim.Status.PAID, Claim.Status.CLOSED} else None,
                "result_sent_by": specialist if status in {Claim.Status.APPROVED, Claim.Status.REJECTED, Claim.Status.PAID, Claim.Status.CLOSED} else None,
            },
            verify_fields=(
                "source_claim_number", "person", "company_snapshot", "contract", "insurer",
                "service_type", "requested_amount",
            ),
        )
        seeded_claims.append(claim)

    # A claim workflow and objection exercise role authorization, SLA, and 60-day objection windows.
    claim_for_flow = seeded_claims[1]
    _ensure_workflow(claim_for_flow, "claim_review", head, specialist, note="آغاز ارزیابی خسارت نمونه")
    objection_claim = seeded_claims[4]
    objection, _ = record(
        ClaimObjection,
        {"claim": objection_claim, "description": "اعتراض نمونه به مبلغ ارزیابی‌شده پرونده."},
        {
            "submitted_by": users["employee.a"],
            "status": ClaimObjection.Status.OPEN,
            "response": "",
            "deadline_at": objection_claim.result_sent_at + timedelta(days=60),
        },
        verify_fields=("submitted_by",),
    )
    _ensure_workflow(
        objection, "claim_objection", head, specialist,
        note="ارجاع اعتراض برای بررسی نمونه",
    )

    # Payment ledger rows include partial, paid, and reversal scenarios.
    for index, claim in enumerate(seeded_claims, start=1):
        if claim.paid_amount <= 0:
            continue
        payment_amount = Decimal("250000") if index == 7 else claim.paid_amount
        payment, _ = record(
            ClaimPayment,
            {"claim": claim, "entry_type": ClaimPayment.EntryType.PAYMENT, "source_reference": f"DEMO-VOUCHER-{index:03d}"},
            {
                "amount": payment_amount,
                "paid_at": claim.payment_date or today,
                "source_insurer": claim.insurer,
                "recorded_by": insurer_rep,
                "confirmed_by": head,
                "note": "پرداخت نمونه منتقل‌شده از منبع؛ فاقد انتقال وجه واقعی.",
                "is_legacy_import": True,
            },
        )
        if index == 7:
            record(
                ClaimPayment,
                {"claim": claim, "entry_type": ClaimPayment.EntryType.REVERSAL, "reverses_payment": payment},
                {
                    "amount": Decimal("50000"),
                    "paid_at": today,
                    "source_reference": f"DEMO-VOUCHER-{index:03d}",
                    "source_insurer": claim.insurer,
                    "note": "برگشت بخشی از پرداخت برای تست سابقه اصلاح.",
                    "recorded_by": specialist,
                    "confirmed_by": head,
                    "is_legacy_import": False,
                },
            )

    # Contract revision approval remains pending until the authorized final approver closes it.
    revision_contract = line_contracts[InsuranceLine.FIRE]
    snapshot = {
        "code": revision_contract.code,
        "title": revision_contract.title,
        "insurer_id": revision_contract.insurer_id,
        "line": revision_contract.line,
        "start_date": revision_contract.start_date.isoformat(),
        "end_date": revision_contract.end_date.isoformat(),
        "coverage_summary": revision_contract.coverage_summary,
        "terms": revision_contract.terms,
        "company_ids": sorted(revision_contract.companies.values_list("pk", flat=True)),
    }
    revision, _ = record(
        ContractRevision,
        {"contract": revision_contract, "revision_number": 1},
        {
            "description": "نسخه اولیه نمونه برای گردش تصویب قرارداد.",
            "created_by": specialist,
            "status": ContractRevision.Status.PENDING_APPROVAL,
            "snapshot": snapshot,
            "effective_date": today + timedelta(days=1),
        },
        verify_fields=("description", "created_by"),
    )
    _ensure_workflow(revision, "contract_approval", specialist, head, note="ارسال نسخه قرارداد برای تصویب")

    # Asset portfolio across vehicle, property, equipment, other, and person-owned cases.
    asset_specs = (
        ("DEMO-ASSET-VEH-001", InsuredAsset.Type.VEHICLE, company_a, None, line_contracts[InsuranceLine.THIRD_PARTY], "خودروی سازمانی نمونه"),
        ("DEMO-ASSET-VEH-002", InsuredAsset.Type.VEHICLE, company_b, None, line_contracts[InsuranceLine.BODY], "خودروی پشتیبانی نمونه"),
        ("DEMO-ASSET-PROP-001", InsuredAsset.Type.PROPERTY, company_a, None, line_contracts[InsuranceLine.FIRE], "ساختمان اداری نمونه"),
        ("DEMO-ASSET-PROP-002", InsuredAsset.Type.PROPERTY, company_d, None, line_contracts[InsuranceLine.FIRE], "انبار نمونه"),
        ("DEMO-ASSET-EQ-001", InsuredAsset.Type.EQUIPMENT, company_c, None, line_contracts[InsuranceLine.FIRE], "تجهیزات خط تولید نمونه"),
        ("DEMO-ASSET-OTH-001", InsuredAsset.Type.OTHER, company_b, None, line_contracts[InsuranceLine.OTHER], "دارایی متفرقه نمونه"),
        ("DEMO-ASSET-PER-001", InsuredAsset.Type.OTHER, None, employee_a, line_contracts[InsuranceLine.HEALTH], "دارایی شخصی بیمه‌شده نمونه"),
        ("DEMO-ASSET-VEH-003", InsuredAsset.Type.VEHICLE, company_c, None, line_contracts[InsuranceLine.THIRD_PARTY], "خودروی واحد عملیاتی نمونه"),
    )
    assets = []
    for index, (code, asset_type, company, person, contract, name) in enumerate(asset_specs, start=1):
        asset, _ = record(
            InsuredAsset,
            {"asset_code": code},
            {
                "name": name,
                "asset_type": asset_type,
                "company": company,
                "person": person,
                "identifier": f"DEMO-REG-{index:04d}",
                "location": "محوطه نمونه شرکت",
                "insured_value": Decimal(str(100000000 + index * 2500000)),
                "insurer": contract.insurer,
                "contract": contract,
                "policy_number": f"DEMO-POL-{index:04d}",
                "policy_start": start_date,
                "policy_end": end_date,
                "is_active": True,
                "notes": "داده ساختگی برای آزمون دارایی بیمه‌شده.",
                "created_by": specialist,
            },
            verify_fields=(),
        )
        assets.append(asset)
        if asset_type == InsuredAsset.Type.VEHICLE:
            ensure(
                Vehicle,
                {"asset": asset},
                {
                    "plate_number": f"ایران 11-{index:02d}-123 الف",
                    "vin": f"DEMO-VIN-{index:06d}",
                    "engine_number": f"DEMO-ENG-{index:06d}",
                    "make": "سازنده نمونه",
                    "model_name": "مدل آزمایشی",
                    "model_year": 2023 + index % 3,
                },
            )

    valuations = []
    valuation_statuses = (
        AssetValuation.Status.PENDING_APPROVAL,
        AssetValuation.Status.APPROVED,
        AssetValuation.Status.REJECTED,
        AssetValuation.Status.LEGACY,
    )
    for index, asset in enumerate(assets[:4], start=1):
        status = valuation_statuses[index - 1]
        valuation, _ = record(
            AssetValuation,
            {"asset": asset, "source_reference": f"DEMO-VAL-{index:03d}"},
            {
                "valuation_date": today - timedelta(days=index * 5),
                "market_value": Decimal(str(110000000 + index * 1000000)),
                "insured_value": Decimal(str(100000000 + index * 1000000)),
                "method": (AssetValuation.Method.FORMAL, AssetValuation.Method.EXPERT, AssetValuation.Method.DECLARED, AssetValuation.Method.LEGACY)[index - 1],
                "status": status,
                "note": "ارزیابی نمونه غیرواقعی.",
                "created_by": specialist,
                "approved_by": head if status == AssetValuation.Status.APPROVED else None,
            },
            verify_fields=("source_reference", "created_by"),
        )
        valuations.append(valuation)
    _ensure_workflow(valuations[0], "asset_valuation_approval", specialist, head, note="درخواست تأیید ارزیابی نمونه")

    policy_periods = []
    for index, asset in enumerate(assets[:4], start=1):
        contract = asset.contract
        status = AssetPolicyPeriod.Status.PENDING_APPROVAL if index == 1 else (
            AssetPolicyPeriod.Status.ACTIVE if index == 2 else AssetPolicyPeriod.Status.DRAFT
        )
        period, _ = record(
            AssetPolicyPeriod,
            {"policy_number": f"DEMO-ASSET-POL-{index:03d}"},
            {
                "asset": asset, "insurer": contract.insurer, "contract": contract,
                "policy_start": start_date, "policy_end": end_date,
                "status": status, "source_reference": f"DEMO-POL-SOURCE-{index:03d}",
                "note": "دوره بیمه‌نامه نمونه.",
                "created_by": specialist,
                "approved_by": head if status == AssetPolicyPeriod.Status.ACTIVE else None,
            },
            verify_fields=("asset", "insurer", "contract", "policy_start", "policy_end", "source_reference", "created_by"),
        )
        policy_periods.append(period)
    _ensure_workflow(policy_periods[0], "asset_policy_approval", specialist, head, note="ارسال دوره بیمه‌نامه برای تأیید")

    endorsement = ensure(
        AssetPolicyEndorsement,
        {"policy_period": policy_periods[0], "endorsement_number": "DEMO-END-001"},
        {
            "effective_date": today + timedelta(days=10),
            "description": "الحاقیه نمونه برای افزایش سقف پوشش دارایی.",
            "document": _content("demo-asset-endorsement.pdf", b"%PDF-1.4\nDemo endorsement fixture\n%%EOF"),
            "status": AssetPolicyEndorsement.Status.PENDING_APPROVAL,
            "created_by": specialist,
            "approved_by": None,
        },
        verify_fields=("description", "created_by"),
    )
    _ensure_workflow(endorsement, "asset_endorsement_approval", specialist, head, note="ارجاع الحاقیه دارایی برای تأیید")

    # Scoped delegations (active and suspended) plus immutable event history.
    delegation_specs = (
        ("medical_assistance", "medical_assistance", RoleAssignment.Role.SUBSIDIARY_REP, company_rep_a, company_a, None, "health", WorkDelegation.Status.ACTIVE),
        ("person_change", "iban", RoleAssignment.Role.INSURER_REP, insurer_rep, None, insurer, "health", WorkDelegation.Status.SUSPENDED),
        ("claim_review", "", RoleAssignment.Role.INSURANCE_SPECIALIST, specialist, None, None, "health", WorkDelegation.Status.ACTIVE),
    )
    delegations = []
    for code, item_type, role, delegate, company, insurer_obj, line, status in delegation_specs:
        delegation, _ = record(
            WorkDelegation,
            {
                "workflow_code": code, "item_type": item_type,
                "delegate_role": role, "delegate_to": delegate,
                "granted_by": head, "company": company,
                "insurer": insurer_obj, "line_code": line,
            },
            {
                "reason": "تفویض نمونه محدود به فرآیند، زیرنوع و محدوده مشخص؛ قابل ممیزی.",
                "status": status, "valid_from": today - timedelta(days=3),
                "valid_until": today + timedelta(days=30),
                "revocation_reason": "تعلیق آزمایشی" if status == WorkDelegation.Status.SUSPENDED else "",
            },
            verify_fields=("reason", "delegate_role", "delegate_to", "granted_by"),
        )
        delegations.append(delegation)
        ensure(
            DelegationEvent,
            {"delegation": delegation, "event_type": DelegationEvent.EventType.CREATED},
            {"actor": head, "summary": "تفویض نمونه ایجاد شد.", "metadata": {"fixture": "DEMO-SEED"}},
        )
        if status == WorkDelegation.Status.SUSPENDED:
            ensure(
                DelegationEvent,
                {"delegation": delegation, "event_type": DelegationEvent.EventType.SUSPENDED},
                {"actor": head, "summary": "تفویض نمونه به حالت تعلیق درآمد.", "metadata": {"fixture": "DEMO-SEED"}},
            )

    # Document vault: normal, internal, confidential, medical, archived and voided examples.
    from documents.services import (
        add_document_version, archive_document, create_document,
        record_document_access, void_document,
    )
    document_specs = (
        ("سند اداری نمونه شرکت الف", "نامه", company_a, employee_a, DocumentRecord.SecurityLevel.NORMAL, False),
        ("سند داخلی قرارداد نمونه", "قرارداد", company_a, None, DocumentRecord.SecurityLevel.INTERNAL, False),
        ("سند محرمانه منابع انسانی", "پرسنلی", company_b, employee_b, DocumentRecord.SecurityLevel.CONFIDENTIAL, False),
        ("سند پزشکی محرمانه نمونه", "پزشکی", company_a, employee_a, DocumentRecord.SecurityLevel.VERY_CONFIDENTIAL, True),
        ("سند قابل بایگانی نمونه", "بایگانی", company_c, None, DocumentRecord.SecurityLevel.INTERNAL, False),
        ("سند باطل‌شده نمونه", "باطل‌شده", company_d, None, DocumentRecord.SecurityLevel.CONFIDENTIAL, False),
    )
    documents = []
    for index, (title, category, company, person, security, medical) in enumerate(document_specs, start=1):
        document = DocumentRecord.objects.filter(title=title, category=category).first()
        if not document:
            document = create_document(
                title=title,
                category=category,
                upload=_content(f"demo-document-{index:02d}.pdf", b"%PDF-1.4\nSynthetic office_kmc demo document\n%%EOF"),
                uploaded_by=specialist,
                company=company,
                person=person,
                security_level=security,
                is_medical=medical,
                change_reason="نسخه اولیه داده نمونه",
            )
        documents.append(document)
        if document.versions.count() < 2 and not document.is_archived and not document.is_void:
            add_document_version(
                document_id=document.pk,
                upload=_content(f"demo-document-{index:02d}-v2.pdf", b"%PDF-1.4\nSynthetic revised demo document\n%%EOF"),
                uploaded_by=head,
                change_reason="نسخه دوم برای آزمون تاریخچه نسخه",
            )
        if index == 5 and not document.is_archived:
            archive_document(document_id=document.pk, actor=head, reason="بایگانی سناریوی نمونه")
            document.refresh_from_db()
        if index == 6 and not document.is_void:
            void_document(document_id=document.pk, actor=head, reason="ابطال سناریوی نمونه")
            document.refresh_from_db()
        if not DocumentAccessEvent.objects.filter(document=document, actor=head, action=DocumentAccessEvent.Action.VIEW).exists():
            version = document.current_version
            if version:
                record_document_access(document=document, version=version, actor=head, action=DocumentAccessEvent.Action.VIEW)
    claim_content_type = ContentType.objects.get_for_model(Claim, for_concrete_model=False)
    person_content_type = ContentType.objects.get_for_model(Person, for_concrete_model=False)
    for document, target, content_type in (
        (documents[0], seeded_claims[0], claim_content_type),
        (documents[2], employee_b, person_content_type),
        (documents[3], employee_a, person_content_type),
    ):
        ensure(
            DocumentLink,
            {"document": document, "content_type": content_type, "object_id": str(target.pk)},
            {"created_by": specialist},
        )

    # Announcements cover audience and publication windows.
    announcement_specs = (
        ("DEMO-ANN-ALL", Announcement.Audience.ALL, None, True, timezone.make_aware(datetime(2026, 11, 9, 8, 0)), None),
        ("DEMO-ANN-STAFF", Announcement.Audience.STAFF, None, True, timezone.make_aware(datetime(2026, 11, 10, 8, 0)), None),
        ("DEMO-ANN-COMPANY", Announcement.Audience.SUBSIDIARY, company_a, True, timezone.make_aware(datetime(2026, 11, 11, 8, 0)), timezone.make_aware(datetime(2026, 11, 18, 8, 0))),
        ("DEMO-ANN-EMP", Announcement.Audience.EMPLOYEES, company_b, False, timezone.make_aware(datetime(2026, 11, 12, 8, 0)), None),
        ("DEMO-ANN-INS", Announcement.Audience.INSURERS, None, True, timezone.make_aware(datetime(2026, 11, 7, 8, 0)), timezone.make_aware(datetime(2026, 11, 10, 8, 0))),
    )
    for title, audience, company, published, publish_at, expires_at in announcement_specs:
        ensure(
            Announcement,
            {"title": title},
            {
                "body": f"متن ساختگی اطلاعیه {title} برای آزمون مخاطب و بازه انتشار.",
                "audience": audience, "company": company,
                "is_published": published, "publish_at": publish_at,
                "expires_at": expires_at, "created_by": head,
            },
            verify_fields=(),
        )

    # Notifications cover unread/read states and internal target URLs.
    for index, recipient in enumerate((
        admin, head, specialist, company_rep_a, company_rep_b, users["employee.a"],
        users["employee.b"], insurer_rep, fire_specialist, second_insurer_user,
        company_c_rep, company_d_rep,
    ), start=1):
        ensure(
            UserNotification,
            {"recipient": recipient, "title": f"اعلان نمونه {index:02d}"},
            {
                "actor": head,
                "body": f"این اعلان ساختگی شماره {index} برای آزمون صندوق اعلانات است.",
                "target_url": "/dashboard/",
                "read_at": now - timedelta(hours=index) if index % 3 == 0 else None,
            },
            verify_fields=(),
        )

    # Use the application's central sequence service so demo numbers never collide.
    from correspondence.services import next_internal_number

    correspondence_rows = []
    correspondence_specs = (
        (Correspondence.Direction.INBOUND, Correspondence.Channel.LETTER, company_a, insurer, line_contracts[InsuranceLine.HEALTH], Correspondence.FollowUp.PENDING, False),
        (Correspondence.Direction.OUTBOUND, Correspondence.Channel.EMAIL, company_b, insurer, line_contracts[InsuranceLine.HEALTH], Correspondence.FollowUp.COMPLETED, False),
        (Correspondence.Direction.INTERNAL, Correspondence.Channel.MEETING, company_c, insurer_b, line_contracts[InsuranceLine.FIRE], Correspondence.FollowUp.NOT_REQUIRED, True),
        (Correspondence.Direction.INBOUND, Correspondence.Channel.PHONE, company_d, insurer_b, line_contracts[InsuranceLine.LIABILITY], Correspondence.FollowUp.PENDING, False),
        (Correspondence.Direction.OUTBOUND, Correspondence.Channel.PORTAL, company_a, insurer_b, line_contracts[InsuranceLine.FIRE], Correspondence.FollowUp.COMPLETED, True),
        (Correspondence.Direction.INBOUND, Correspondence.Channel.OTHER, company_b, insurer, line_contracts[InsuranceLine.LIFE], Correspondence.FollowUp.NOT_REQUIRED, False),
    )
    for index, (direction, channel, company, corr_insurer, contract, follow_up, confidential) in enumerate(correspondence_specs, start=1):
        external_reference = f"EXT-DEMO-{index:03d}"
        defaults = {
            "subject": f"مکاتبه نمونه {index:02d}",
            "channel": channel, "direction": direction,
            "company": company, "insurer": corr_insurer, "contract": contract,
            "external_reference": external_reference,
            "summary": "خلاصه مکاتبه ساختگی؛ حاوی اطلاعات واقعی نیست.",
            "occurred_at": now - timedelta(days=index),
            "follow_up_due": today + timedelta(days=index),
            "follow_up_status": follow_up,
            "assigned_to": specialist if index % 2 else head,
            "is_confidential": confidential,
            "created_by": head,
        }
        existing = Correspondence.objects.filter(external_reference=external_reference).first()
        number = existing.internal_number if existing else next_internal_number(defaults["occurred_at"])
        item, _ = record(
            Correspondence,
            {"internal_number": number},
            defaults,
            verify_fields=("external_reference", "created_by"),
        )
        correspondence_rows.append(item)
        event_type = (
            CorrespondenceEvent.EventType.REFERRED if index % 2
            else CorrespondenceEvent.EventType.FOLLOW_UP
        )
        ensure(
            CorrespondenceEvent,
            {"correspondence": item, "event_type": CorrespondenceEvent.EventType.CREATED, "summary": "مکاتبه نمونه ثبت شد."},
            {"actor": head, "metadata": {"fixture": "DEMO-SEED"}, "occurred_at": now - timedelta(days=index)},
            verify_fields=("actor", "metadata"),
        )
        ensure(
            CorrespondenceEvent,
            {"correspondence": item, "event_type": event_type, "summary": "رویداد پیگیری نمونه ثبت شد."},
            {"actor": specialist, "metadata": {"step": "demo"}, "occurred_at": now - timedelta(days=index - 1)},
            verify_fields=("actor", "metadata"),
        )
    correspondence_solar_days = {item.internal_number[:8] for item in correspondence_rows}
    correspondence_solar_day = correspondence_rows[0].internal_number[:8]
    if CorrespondenceSequence.objects.filter(solar_date__in=correspondence_solar_days).count() != len(correspondence_solar_days):
        raise CommandError("A demo correspondence serial has no matching central sequence row.")
    claim_content_type = ContentType.objects.get_for_model(Claim, for_concrete_model=False)
    for index, item in enumerate(correspondence_rows[:3], start=1):
        ensure(
            CorrespondenceLink,
            {"correspondence": item, "content_type": claim_content_type, "object_id": str(seeded_claims[index - 1].pk)},
            {"created_by": head},
        )

    # ImportBatch rows make each lifecycle state visible without creating live data from fixtures.
    people_xlsx = _sample_xlsx(
        "demo-people-roster.xlsx",
        ["action", "national_id", "first_name", "last_name", "birth_date"],
        ["add_employee", "0012345690", "نمونه", "ورودی", "1990-01-01"],
    )
    claims_xlsx = _sample_xlsx(
        "demo-claims.xlsx",
        ["claim_number", "national_id", "service_type", "contract_number"],
        ["INS-DEMO-9001", "0012345678", "ویزیت نمونه", "DEMO-1405"],
    )
    contract_xlsx = _sample_xlsx(
        "demo-contracts.xlsx",
        ["code", "title", "insurer_name", "line"],
        ["DEMO-IMPORT-CONTRACT", "قرارداد نمونه", insurer.name, "health"],
    )
    import_specs = (
        ("DEMO-IMPORT-PEOPLE", "people_roster", ImportBatch.Status.UPLOADED, people_xlsx),
        ("DEMO-IMPORT-CLAIMS", "claims", ImportBatch.Status.FAILED, claims_xlsx),
        ("DEMO-IMPORT-CONTRACT", "contracts", ImportBatch.Status.PROCESSED, contract_xlsx),
    )
    for batch_number, source_type, status, upload in import_specs:
        ensure(
            ImportBatch,
            {"batch_number": batch_number},
            {
                "source_type": source_type, "file": upload,
                "uploaded_by": company_rep_a if source_type == "people_roster" else insurer_rep if source_type == "claims" else specialist,
                "status": status, "total_rows": 5, "valid_rows": 3, "invalid_rows": 2,
                "result_report": "نمونه گزارش خطا/نتیجه؛ هیچ داده‌ای از این batch به‌صورت خودکار اعمال نمی‌شود.",
                "preview_data": [],
                "column_mapping": {"national_id": "D", "first_name": "Y"},
                "reviewed_by": head if status == ImportBatch.Status.PROCESSED else None,
                "reviewed_at": now if status == ImportBatch.Status.PROCESSED else None,
                "review_note": "تأیید نمونه" if status == ImportBatch.Status.PROCESSED else "",
            },
            verify_fields=("source_type", "uploaded_by", "total_rows", "valid_rows", "invalid_rows", "column_mapping"),
        )

    # Task inbox and immutable task timeline, with a wide mix of urgency/status values.
    task_statuses = (
        InternalTask.Status.OPEN, InternalTask.Status.IN_PROGRESS,
        InternalTask.Status.WAITING, InternalTask.Status.DONE, InternalTask.Status.CANCELLED,
    )
    priorities = (
        InternalTask.Priority.LOW, InternalTask.Priority.NORMAL,
        InternalTask.Priority.HIGH, InternalTask.Priority.URGENT,
    )
    for index in range(1, 13):
        creator = head if index % 2 else specialist
        assignee = specialist if index % 2 else head
        related = service_requests[(index - 1) % len(service_requests)] if service_requests else None
        task = ensure(
            InternalTask,
            {"title": f"وظیفه نمونه {index:02d}"},
            {
                "description": "وظیفه ساختگی برای آزمون اولویت، مهلت، تخصیص و تغییر وضعیت.",
                "created_by": creator,
                "priority": priorities[(index - 1) % len(priorities)],
                "status": task_statuses[(index - 1) % len(task_statuses)],
                "due_at": now + timedelta(days=index - 6),
                "related_request": related,
            },
            verify_fields=(),
        )
        existing_assignees = set(task.assignees.values_list("pk", flat=True))
        if not existing_assignees:
            task.assignees.add(assignee)
        # Preserve an operator-modified assignee list on an existing demo task.
        ensure(
            TaskEvent,
            {"task": task, "event_type": TaskEvent.EventType.CREATED, "note": "ایجاد وظیفه نمونه"},
            {"actor": creator, "from_value": "", "to_value": task.status, "occurred_at": now - timedelta(days=index)},
            verify_fields=("actor", "from_value"),
        )
        ensure(
            TaskEvent,
            {"task": task, "event_type": TaskEvent.EventType.ASSIGNED, "note": "تخصیص وظیفه نمونه"},
            {"actor": creator, "from_value": "", "to_value": assignee.username, "occurred_at": now - timedelta(days=index - 1)},
            verify_fields=("actor", "from_value"),
        )

    # Calendar fixtures include holidays and an explicit exceptional working day.
    calendar = ensure(
        BusinessCalendar,
        {"code": "demo-iran-calendar"},
        {
            "title": "تقویم کاری نمونه مجموعه",
            "timezone_name": "Asia/Tehran",
            "working_weekdays": [5, 6, 0, 1, 2, 3],
            "start_time": datetime.strptime("08:00", "%H:%M").time(),
            "end_time": datetime.strptime("16:00", "%H:%M").time(),
            "is_active": True,
        },
        verify_fields=(),
    )
    holiday_specs = (
        (date(2026, 3, 21), "تعطیلی نمونه نوروز", False),
        (date(2026, 3, 22), "تعطیلی نمونه دوم", False),
        (date(2026, 4, 1), "تعطیلی مناسبتی نمونه", False),
        (date(2026, 4, 3), "روز کاری استثنایی نمونه", True),
        (date(2026, 12, 1), "تعطیلی آتی نمونه", False),
    )
    for holiday_date, title, override in holiday_specs:
        ensure(
            CalendarHoliday,
            {"calendar": calendar, "date": holiday_date},
            {"title": title, "is_working_override": override},
            verify_fields=(),
        )

    # Extra append-only audit records exercise before/after/metadata and object references.
    audit_specs = (
        ("demo_company_scope_checked", "Company", company_a.pk, "محدوده شرکت نمونه بررسی شد."),
        ("demo_contract_reviewed", "Contract", line_contracts[InsuranceLine.FIRE].pk, "قرارداد نمونه برای بررسی آماده شد."),
        ("demo_claim_imported", "Claim", seeded_claims[0].pk, "خسارت نمونه در سناریوی داده‌ای ثبت شد."),
        ("demo_asset_registered", "InsuredAsset", assets[0].pk, "دارایی نمونه ثبت شد."),
        ("demo_document_access", "DocumentRecord", documents[0].pk, "دسترسی نمونه به سند ثبت شد."),
        ("demo_delegation_created", "WorkDelegation", delegations[0].pk, "تفویض نمونه ثبت شد."),
    )
    for action, object_type, object_id, summary in audit_specs:
        ensure(
            AuditEvent,
            {"action": action, "object_type": object_type, "object_id": str(object_id), "summary": summary},
            {
                "actor": head,
                "before_data": {},
                "after_data": {"fixture": "DEMO-SEED", "object_id": str(object_id)},
                "metadata": {"synthetic": True, "scope": "local-demo"},
            },
        )

    # Verify that a namespaced demo fixture exists in each of the 45 concrete models.
    solar_day = correspondence_solar_day
    demo_usernames = (
        "admin.demo", "head.demo", "specialist.demo", "companya.demo",
        "companyb.demo", "employee.a", "employee.b", "insurer.demo",
        "specialist.fire.demo", "insurer.two.demo", "companyc.demo", "companyd.demo",
    )
    service_workflow_codes = [code for code, _label in ServiceRequest.Kind.choices]
    coverage_checks = {
        "accounts.user": User.objects.filter(username__in=demo_usernames).count() >= len(demo_usernames),
        "accounts.organizationalunit": OrganizationalUnit.objects.filter(code__startswith="DEMO-").exists(),
        "accounts.organizationalposition": OrganizationalPosition.objects.filter(code__startswith="DEMO-").exists(),
        "accounts.roleassignment": RoleAssignment.objects.filter(user__username__in=demo_usernames).exists(),
        "accounts.positionassignment": PositionAssignment.objects.filter(position__code__startswith="DEMO-").exists(),
        "accounts.usernotification": UserNotification.objects.filter(title__startswith="اعلان نمونه").exists(),
        "announcements.announcement": Announcement.objects.filter(title__startswith="DEMO-ANN").exists(),
        "assets.insuredasset": InsuredAsset.objects.filter(asset_code__startswith="DEMO-ASSET").exists(),
        "assets.vehicle": Vehicle.objects.filter(asset__asset_code__startswith="DEMO-ASSET-VEH").exists(),
        "assets.assetvaluation": AssetValuation.objects.filter(asset__asset_code__startswith="DEMO-ASSET").exists(),
        "assets.assetpolicyperiod": AssetPolicyPeriod.objects.filter(policy_number__startswith="DEMO-ASSET-POL").exists(),
        "assets.assetpolicyendorsement": AssetPolicyEndorsement.objects.filter(endorsement_number__startswith="DEMO-END").exists(),
        "auditlog.auditevent": AuditEvent.objects.filter(action__startswith="demo_").exists(),
        "claims.claim": Claim.objects.filter(claim_number__startswith="DEMO-FULL-CLM").exists(),
        "claims.claimpayment": ClaimPayment.objects.filter(source_reference__startswith="DEMO-VOUCHER").exists(),
        "claims.claimobjection": ClaimObjection.objects.filter(description__startswith="اعتراض نمونه").exists(),
        "correspondence.correspondencesequence": CorrespondenceSequence.objects.filter(solar_date=solar_day).exists(),
        "correspondence.correspondence": Correspondence.objects.filter(internal_number__startswith=solar_day).exists(),
        "correspondence.correspondencelink": CorrespondenceLink.objects.filter(correspondence__internal_number__startswith=solar_day).exists(),
        "correspondence.correspondenceevent": CorrespondenceEvent.objects.filter(summary__contains="نمونه").exists(),
        "delegations.workdelegation": WorkDelegation.objects.filter(reason__contains="تفویض نمونه").exists(),
        "delegations.delegationevent": DelegationEvent.objects.filter(summary__contains="تفویض نمونه").exists(),
        "documents.documentrecord": DocumentRecord.objects.filter(title__contains="نمونه").exists(),
        "documents.documentversion": DocumentVersion.objects.filter(document__title__contains="نمونه").exists(),
        "documents.documentlink": DocumentLink.objects.filter(document__title__contains="نمونه").exists(),
        "documents.documentaccessevent": DocumentAccessEvent.objects.filter(document__title__contains="نمونه").exists(),
        "imports.importbatch": ImportBatch.objects.filter(batch_number__startswith="DEMO-IMPORT").exists(),
        "insurance.insurer": Insurer.objects.filter(name__contains="نمونه").exists(),
        "insurance.contract": Contract.objects.filter(code__startswith="DEMO-").exists(),
        "insurance.contractrevision": ContractRevision.objects.filter(contract__code="DEMO-FIRE-01").exists(),
        "organizations.company": Company.objects.filter(code__in=("DEMO-A", "DEMO-B", "DEMO-C", "DEMO-D")).count() >= 4,
        "organizations.person": Person.objects.filter(national_id__in=("0012345680", "0012345685", "0012345686")).count() >= 3,
        "organizations.personemployment": PersonEmployment.objects.filter(source_reference="DEMO-SEED").exists(),
        "organizations.companyleadershiptitle": CompanyLeadershipTitle.objects.filter(title__in=("مدیر منابع انسانی", "نماینده سلامت و درمان", "مدیر پشتیبانی", "مدیر عملیات")).exists(),
        "organizations.personchangerequest": PersonChangeRequest.objects.filter(reason__contains="درخواست آزمایشی اصلاح اطلاعات").exists(),
        "requests_portal.servicerequest": ServiceRequest.objects.filter(reference__startswith="DEMO-REQ").exists(),
        "tasks.internaltask": InternalTask.objects.filter(title__startswith="وظیفه نمونه").exists(),
        "tasks.taskevent": TaskEvent.objects.filter(note__contains="وظیفه نمونه").exists(),
        "workflow.workflowdefinition": WorkflowDefinition.objects.filter(code__in=service_workflow_codes, is_active=True).exists(),
        "workflow.workflowstep": WorkflowStep.objects.filter(definition__code__in=service_workflow_codes).exists(),
        "workflow.workflowtransition": WorkflowTransition.objects.filter(definition__code__in=service_workflow_codes).exists(),
        "workflow.workflowcase": WorkflowCase.objects.filter(definition__code__in=service_workflow_codes).exists(),
        "workflow.workflowevent": WorkflowEvent.objects.filter(workflow_case__definition__code__in=service_workflow_codes).exists(),
        "workflow.businesscalendar": BusinessCalendar.objects.filter(code="demo-iran-calendar").exists(),
        "workflow.calendarholiday": CalendarHoliday.objects.filter(calendar__code="demo-iran-calendar").exists(),
    }
    missing = [label for label in EXPECTED_MODEL_LABELS if not coverage_checks.get(label, False)]
    if len(coverage_checks) != len(EXPECTED_MODEL_LABELS):
        raise CommandError(
            f"Coverage manifest has {len(coverage_checks)} checks for {len(EXPECTED_MODEL_LABELS)} models."
        )
    if missing:
        raise CommandError("Demo seed incomplete; missing demo fixtures for: " + ", ".join(missing))

    fixture_rows = (
        sum(created_counts.values()) + sum(reused_counts.values())
        if created_counts is not None and reused_counts is not None else 0
    )
    if fixture_rows < 100:
        raise CommandError(f"Demo seed must create or recover at least 100 fixture rows; found {fixture_rows}.")

    return {
        "model_coverage": len(EXPECTED_MODEL_LABELS),
        "fixture_rows": fixture_rows,
        "total_model_rows": sum(apps.get_model(label).objects.count() for label in EXPECTED_MODEL_LABELS),
        "additional_users": tuple(extra_users),
        "additional_users_created": tuple(additional_users_created),
        "service_requests": len(service_requests),
        "claims": len(seeded_claims),
        "assets": len(assets),
        "documents": len(documents),
        "work_delegations": len(delegations),
    }
