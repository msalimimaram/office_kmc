"""Presentation-grade, deterministic fixture expansion for office_kmc.

This module is intentionally separate from the normal application workflows.
It creates synthetic, namespaced records only and fails closed when a model
cannot reach its declared coverage floor.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta
import os

import jdatetime
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management.base import CommandError
from django.db import IntegrityError, models, transaction
from django.utils import timezone
from openpyxl import Workbook
from io import BytesIO


MINIMUM_PER_MODEL = 50


def _count(model):
    return model._base_manager.count()


def _sample_xlsx(filename, category, index):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Demo"
    sheet.append(["شناسه", "نوع سناریو", "شماره نمونه", "توضیحات"])
    sheet.append([f"DEMO-{category}-{index:04d}", category, index, "داده ساختگی برای ارائه"])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return ContentFile(buffer.getvalue(), name=filename)


def _ensure_user(*, username, role, company=None, insurer=None, national_id="", first_name="", last_name="", mobile=""):
    from accounts.models import User

    password = os.environ.get("PRESENTATION_DEMO_PASSWORD", "")
    if not password:
        raise CommandError("PRESENTATION_DEMO_PASSWORD is required before presentation accounts can be created.")

    defaults = {
        "role": role,
        "company": company,
        "insurer": insurer,
        "national_id": national_id,
        "first_name": first_name,
        "last_name": last_name,
        "mobile": mobile,
        "is_active": True,
        "must_change_password": False,
        "is_staff": False,
    }
    user = User.objects.filter(username=username).first()
    if user is None:
        user = User(username=username, **defaults)
        user.set_password(password)
        user.save()
        return user

    for field in ("role", "company", "insurer", "is_active"):
        if getattr(user, field) != defaults[field]:
            raise CommandError(f"Demo account collision: {username}.{field} does not match its declared presentation scope.")
    changed = []
    if national_id and not user.national_id:
        user.national_id = national_id
        changed.append("national_id")
    elif national_id and user.national_id != national_id:
        raise CommandError(f"Demo account collision: {username} has a different national ID.")
    for field in ("first_name", "last_name", "mobile"):
        if not getattr(user, field) and defaults[field]:
            setattr(user, field, defaults[field])
            changed.append(field)
    if not user.has_usable_password():
        user.set_password(password)
        changed.append("password")
    if user.must_change_password:
        user.must_change_password = False
        changed.append("must_change_password")
    if changed:
        user.save(update_fields=changed)
    return user


def _ensure_role_assignment(record, *, user, role, company=None, insurer=None, line_code="", granted_by, approved_by, reason):
    from accounts.models import RoleAssignment

    return record(
        RoleAssignment,
        {
            "user": user,
            "role": role,
            "company": company,
            "insurer": insurer,
            "line_code": line_code,
        },
        {
            "valid_from": date(2026, 1, 1),
            "valid_until": None,
            "is_active": True,
            "reason": reason,
            "granted_by": granted_by,
            "approved_by": approved_by,
        },
        verify_fields=(),
    )[0]


def _make_unique_value(field, old_value, token):
    internal = field.get_internal_type()
    if field.is_relation:
        if field.name in {"content_type"}:
            return old_value
        related = field.remote_field.model
        candidates = list(related._base_manager.exclude(pk=old_value).order_by("pk").values_list("pk", flat=True)[:500])
        return candidates[(token - 1) % len(candidates)] if candidates else old_value
    if field.name == "solar_date":
        return jdatetime.date.fromgregorian(date=date(2026, 1, 1) + timedelta(days=token)).strftime("%Y%m%d")
    if internal in {"DateField"}:
        return (old_value or date(2026, 1, 1)) + timedelta(days=token)
    if internal in {"DateTimeField"}:
        return (old_value or timezone.now()) + timedelta(days=token)
    if internal in {"UUIDField"}:
        import uuid
        return uuid.uuid5(uuid.NAMESPACE_URL, f"office-kmc:{field.model._meta.label_lower}:{token}")
    if internal in {"IntegerField", "BigIntegerField", "PositiveIntegerField", "PositiveSmallIntegerField", "SmallIntegerField", "AutoField", "BigAutoField"}:
        return int(old_value or 0) + token
    if internal in {"DecimalField", "FloatField"}:
        return (old_value or 0) + token
    max_length = getattr(field, "max_length", None) or 120
    if field.name in {"email", "contact_email"}:
        candidate = f"demo-{field.model._meta.model_name}-{token:04d}@example.invalid"
    else:
        candidate = f"DEMO-{field.model._meta.model_name.upper()}-{token:04d}"
    return candidate[:max_length]


def _unique_field_groups(model):
    groups = []
    for field in model._meta.concrete_fields:
        if field.unique and not field.primary_key:
            groups.append((field.name,))
    for constraint in model._meta.constraints:
        if isinstance(constraint, models.UniqueConstraint) and constraint.fields:
            groups.append(tuple(constraint.fields))
    for group in getattr(model._meta, "unique_together", ()) or ():
        groups.append(tuple(group))
    return groups


def _clone_until_minimum(model, *, target=MINIMUM_PER_MODEL, created_counts=None, preferred_sources=None):
    """Clone already-valid synthetic archetypes while changing natural keys.

    Model-specific lifecycle records are handled before this fallback. Every
    clone passes the model's normal save()/full_clean() path; no bulk_create,
    QuerySet.update, or constraint bypass is used.
    """
    if _count(model) >= target:
        return
    source_rows = list(preferred_sources or model._base_manager.order_by("pk"))
    if not source_rows:
        raise CommandError(f"No valid fixture archetype exists for {model._meta.label}; cannot create presentation examples.")

    sequence = _count(model)
    failures = []
    while _count(model) < target:
        token = sequence + 1
        created = None
        attempts = max(1, min(len(source_rows), 100))
        for attempt in range(attempts):
            source = source_rows[(token + attempt - 1) % len(source_rows)]
            values = {}
            for field in model._meta.concrete_fields:
                if field.primary_key or field.auto_created:
                    continue
                if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
                    continue
                value = getattr(source, field.attname)
                if isinstance(field, models.FileField):
                    value = value.name if value else ""
                elif isinstance(field, models.JSONField):
                    value = deepcopy(value)
                values[field.attname] = value

            for group in _unique_field_groups(model):
                # Prefer a scalar key in a composite constraint; special
                # relationship cases are adjusted below.
                candidates = [model._meta.get_field(name) for name in group]
                field = next(
                    (f for f in reversed(candidates) if f.get_internal_type() in {
                        "CharField", "SlugField", "EmailField", "DateField", "DateTimeField",
                        "IntegerField", "BigIntegerField", "PositiveIntegerField",
                    }),
                    candidates[0],
                )
                old = values.get(field.attname)
                values[field.attname] = _make_unique_value(field, old, token + attempt)

            label = model._meta.label_lower
            if label == "documents.documentversion":
                current_max = model._base_manager.filter(document_id=values["document_id"]).aggregate(v=models.Max("version_number"))["v"] or 0
                values["version_number"] = current_max + 1
                values["is_current"] = False
            elif label == "organizations.personchangerequest":
                from organizations.models import PersonChangeRequest
                values["status"] = PersonChangeRequest.Status.REJECTED
                values["rejected_by_id"] = values.get("rejected_by_id") or values.get("approved_by_id")
                values["rejected_at"] = values.get("rejected_at") or timezone.now()
            elif label == "assets.assetpolicyendorsement":
                from assets.models import AssetPolicyEndorsement
                choices = list(AssetPolicyEndorsement.Status.values)
                status = choices[(token - 1) % len(choices)]
                values["status"] = status
                if status == AssetPolicyEndorsement.Status.APPROVED:
                    values["approved_by_id"] = values.get("approved_by_id") or values.get("created_by_id")
            elif label == "claims.claimobjection":
                from claims.models import ClaimObjection
                choices = list(ClaimObjection.Status.values)
                status = choices[(token - 1) % len(choices)]
                values["status"] = status
                if status in {ClaimObjection.Status.ANSWERED, ClaimObjection.Status.CLOSED}:
                    values["response"] = f"پاسخ نمایشی سناریوی {token:04d}"
            elif label == "imports.importbatch":
                from imports.models import ImportBatch
                choices = list(ImportBatch.Status.values)
                values["status"] = choices[(token - 1) % len(choices)]
            elif label == "tasks.internaltask":
                from tasks.models import InternalTask
                values["status"] = list(InternalTask.Status.values)[(token - 1) % len(InternalTask.Status.values)]
                values["priority"] = list(InternalTask.Priority.values)[(token - 1) % len(InternalTask.Priority.values)]
            elif label == "tasks.taskevent":
                from tasks.models import TaskEvent
                values["event_type"] = list(TaskEvent.EventType.values)[(token - 1) % len(TaskEvent.EventType.values)]
            elif label == "announcements.announcement":
                from announcements.models import Announcement
                values["audience"] = list(Announcement.Audience.values)[(token - 1) % len(Announcement.Audience.values)]
            elif label == "documents.documentaccessevent":
                from documents.models import DocumentAccessEvent
                values["action"] = list(DocumentAccessEvent.Action.values)[(token - 1) % len(DocumentAccessEvent.Action.values)]
            elif label == "correspondence.correspondenceevent":
                from correspondence.models import CorrespondenceEvent
                values["event_type"] = list(CorrespondenceEvent.EventType.values)[(token - 1) % len(CorrespondenceEvent.EventType.values)]
            elif label == "delegations.delegationevent":
                from delegations.models import DelegationEvent
                values["event_type"] = list(DelegationEvent.EventType.values)[(token - 1) % len(DelegationEvent.EventType.values)]
            elif label == "workflow.workflowevent":
                from workflow.models import WorkflowEvent
                values["event_type"] = list(WorkflowEvent.EventType.values)[(token - 1) % len(WorkflowEvent.EventType.values)]

            # Append recognizable, unique scenario text without changing
            # Choice fields or business-critical numerical relationships.
            for field in model._meta.concrete_fields:
                if field.primary_key or field.name not in {
                    "title", "subject", "summary", "description", "note", "reason",
                    "external_reference", "source_reference", "batch_number",
                }:
                    continue
                old = values.get(field.attname) or ""
                marker = f" | نمونه ارائه {token:04d}"
                values[field.attname] = (str(old) + marker)[: (field.max_length or 2000)]

            clone = model(**values)
            try:
                with transaction.atomic():
                    clone.save()
                    for field in model._meta.many_to_many:
                        getattr(clone, field.name).set(getattr(source, field.name).all())
                created = clone
                break
            except (ValidationError, IntegrityError, ValueError, TypeError) as exc:
                failures.append(f"{model._meta.label}: {exc}")
                continue

        if created is None:
            detail = failures[-1] if failures else "all valid archetypes were exhausted"
            raise CommandError(f"Unable to expand {model._meta.label} to {target} valid records. Last validation error: {detail}")
        source_rows.append(created)
        sequence += 1
        if created_counts is not None:
            created_counts[model._meta.label] = created_counts.get(model._meta.label, 0) + 1


@transaction.atomic
def expand_presentation_dataset(*, record, users, created_counts, reused_counts, company_a, company_b, company_c, company_d, insurer, insurer_b, employee_a, employee_b, service_requests, seeded_claims, today, now):
    from accounts.models import (
        OrganizationalPosition, OrganizationalUnit, PositionAssignment, RoleAssignment, User, UserNotification,
    )
    from announcements.models import Announcement
    from assets.models import (
        AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle,
    )
    from auditlog.models import AuditEvent
    from claims.models import Claim, ClaimObjection, ClaimPayment
    from correspondence.models import (
        Correspondence, CorrespondenceEvent, CorrespondenceLink, CorrespondenceSequence,
    )
    from delegations.models import DelegationEvent, WorkDelegation
    from documents.models import (
        DocumentAccessEvent, DocumentLink, DocumentRecord, DocumentVersion,
    )
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

    admin = users["admin.demo"]
    head = users["head.demo"]
    health_lead = users["supervisor.demo"]
    health_specialist = users["specialist.demo"]
    fire_specialist = users["specialist.fire.demo"]
    motor_specialist = users["Mahbod"]
    start_date = date(2026, 1, 1)
    end_date = date(2028, 12, 29)

    def ensure(model, lookup, defaults, verify_fields=None):
        return record(model, lookup, defaults, verify_fields)[0]

    # 1) Enterprise scope: one parent, 49 subsidiaries, 50 insurers and
    # named company/insurer representatives. This makes scoping visible.
    companies = [company_a, company_b, company_c, company_d]
    company_index = 5
    while len(companies) < MINIMUM_PER_MODEL:
        company = ensure(
            Company,
            {"code": f"DEMO-PRES-COMP-{company_index:03d}"},
            {
                "name": f"شرکت تابعه نمایشی {company_index:03d}",
                "parent": company_a,
                "is_parent": False,
                "is_active": True,
            },
            verify_fields=(),
        )
        companies.append(company)
        company_index += 1

    insurers = [insurer, insurer_b]
    insurer_index = 3
    while len(insurers) < MINIMUM_PER_MODEL:
        insurer_row = ensure(
            Insurer,
            {"name": f"بیمه‌گر نمایشی شماره {insurer_index:03d}"},
            {
                "contact_name": f"کارشناس بیمه‌گر {insurer_index:03d}",
                "contact_email": f"demo-insurer-{insurer_index:03d}@example.invalid",
                "contact_phone": f"0219000{insurer_index:04d}",
                "is_active": True,
            },
            verify_fields=(),
        )
        insurers.append(insurer_row)
        insurer_index += 1

    company_representatives = {}
    persons_by_company = {}
    health_contracts = {}
    company_users = {}
    insurer_representatives = {}

    for index, company in enumerate(companies, start=1):
        national_id = f"982000{index:04d}"
        representative = _ensure_user(
            username=f"Namayande{index}",
            role=User.Role.SUBSIDIARY_REP,
            company=company,
            national_id=national_id,
            first_name="نماینده",
            last_name=f"شرکت {index:02d}",
            mobile=f"091200{index:06d}",
        )
        company_representatives[company.pk] = representative
        company_users[company.pk] = representative
        users[f"Namayande{index}"] = representative
        _ensure_role_assignment(
            record,
            user=representative,
            role=RoleAssignment.Role.SUBSIDIARY_REP,
            company=company,
            line_code="*",
            granted_by=admin,
            approved_by=head,
            reason="انتصاب نماینده شرکت در داده نمایشی؛ محدود به همان شرکت",
        )
        # A company representative is also an insured employee in the demo,
        # so the same persona can submit requests for self and dependents.
        _ensure_role_assignment(
            record,
            user=representative,
            role=RoleAssignment.Role.INSURED_PERSON,
            company=company,
            line_code="*",
            granted_by=admin,
            approved_by=head,
            reason="ثبت نقش هم‌زمان بیمه‌شده برای نماینده شاغل شرکت",
        )

        person = ensure(
            Person,
            {"national_id": national_id},
            {
                "company": company,
                "user": representative,
                "personnel_code": f"PRES-{index:04d}",
                "first_name": "کاربر",
                "last_name": f"نمایشی {index:02d}",
                "birth_date": date(1980 + (index % 25), 1 + (index % 12), 1 + (index % 27)),
                "relationship": Person.Relationship.EMPLOYEE,
                "employee": None,
                "mobile": representative.mobile,
                "iban": f"IR{index:024d}",
                "is_insured": True,
                "is_active": True,
            },
            verify_fields=("company", "user", "personnel_code", "relationship"),
        )
        persons_by_company[company.pk] = person

        ensure(
            PersonEmployment,
            {"person": person, "company": company, "source_reference": f"DEMO-PRES-EMP-{index:04d}"},
            {
                "personnel_code": person.personnel_code,
                "job_title": "نماینده شرکت / کارمند",
                "valid_from": start_date,
                "valid_until": None,
                "status": PersonEmployment.Status.ACTIVE,
                "created_by": head,
                "approved_by": head,
            },
            verify_fields=("personnel_code", "status"),
        )
        ensure(
            CompanyLeadershipTitle,
            {"company": company, "person": person, "title": "نماینده شرکت"},
            {
                "valid_from": start_date,
                "valid_until": None,
                "declared_by": representative,
            },
            verify_fields=(),
        )

        unit = ensure(
            OrganizationalUnit,
            {"code": f"DEMO-PRES-UNIT-{index:03d}"},
            {
                "name": f"واحد اداری شرکت {index:02d}",
                "parent": None,
                "company": company,
                "is_active": True,
            },
            verify_fields=(),
        )
        level_titles = {
            OrganizationalPosition.Level.DEPUTY: "معاون",
            OrganizationalPosition.Level.DIRECTOR: "مدیر",
            OrganizationalPosition.Level.HEAD: "رئیس",
            OrganizationalPosition.Level.SUPERVISOR: "سرپرست",
            OrganizationalPosition.Level.RESPONSIBLE: "مسئول",
            OrganizationalPosition.Level.SPECIALIST: "کارشناس",
        }
        for level in OrganizationalPosition.Level.values:
            position = ensure(
                OrganizationalPosition,
                {"unit": unit, "code": f"DEMO-COMPANY-LEVEL-{level}"},
                {
                    "title": f"{level_titles[level]} واحد {company.name}",
                    "level": level,
                    "is_active": True,
                },
                verify_fields=(),
            )
            ensure(
                PositionAssignment,
                {"user": representative, "unit": unit, "position": position, "line_code": "*"},
                {
                    "valid_from": start_date,
                    "valid_until": None,
                    "is_active": True,
                    "reason": f"انتصاب نمایشی سمت {level_titles[level]} برای نمایش چندسمتی بودن اشخاص",
                    "granted_by": admin,
                    "approved_by": head,
                },
                verify_fields=(),
            )

    for index, insurer_row in enumerate(insurers, start=1):
        username = "Saman" if index == 1 else f"Saman{index}"
        insurer_user = _ensure_user(
            username=username,
            role=User.Role.INSURER,
            insurer=insurer_row,
            first_name="نماینده",
            last_name=f"بیمه‌گر {index:02d}",
            mobile=f"091233{index:06d}",
        )
        insurer_representatives[insurer_row.pk] = insurer_user
        users[username] = insurer_user
        _ensure_role_assignment(
            record,
            user=insurer_user,
            role=RoleAssignment.Role.INSURER_REP,
            insurer=insurer_row,
            line_code="",
            granted_by=admin,
            approved_by=head,
            reason="انتصاب نماینده بیمه‌گر در محدوده همان بیمه‌گر",
        )

    # Dependents: every relationship type is represented, connected to a
    # valid primary insured person and constrained to the same company.
    dependent_relationships = [
        Person.Relationship.SPOUSE,
        Person.Relationship.CHILD,
        Person.Relationship.FATHER,
        Person.Relationship.MOTHER,
        Person.Relationship.OTHER,
    ]
    dependents_by_company = {}
    for index, company in enumerate(companies, start=1):
        primary = persons_by_company[company.pk]
        relationship = dependent_relationships[(index - 1) % len(dependent_relationships)]
        if relationship == Person.Relationship.CHILD:
            birth = date(2010 + index % 10, 1 + index % 12, 1 + index % 27)
        elif relationship in {Person.Relationship.FATHER, Person.Relationship.MOTHER}:
            birth = date(1950 + index % 20, 1 + index % 12, 1 + index % 27)
        else:
            birth = date(1980 + index % 20, 1 + index % 12, 1 + index % 27)
        dependent = ensure(
            Person,
            {"national_id": f"982100{index:04d}"},
            {
                "company": company,
                "user": None,
                "personnel_code": "",
                "first_name": "عضو خانواده",
                "last_name": f"خانواده {index:03d}",
                "birth_date": birth,
                "relationship": relationship,
                "employee": primary,
                "mobile": f"091288{index:06d}",
                "iban": "",
                "is_insured": True,
                "is_active": True,
            },
            verify_fields=("company", "relationship", "employee"),
        )
        dependents_by_company[company.pk] = dependent

    # Historical employment examples include transfers, retirement and
    # termination without changing the current active employment pointer.
    employment_statuses = [
        PersonEmployment.Status.TRANSFERRED,
        PersonEmployment.Status.RETIRED,
        PersonEmployment.Status.TERMINATED,
    ]
    for index, company in enumerate(companies, start=1):
        person = persons_by_company[company.pk]
        previous_company = companies[index % len(companies)]
        if previous_company.pk == company.pk:
            previous_company = companies[(index + 1) % len(companies)]
        status = employment_statuses[(index - 1) % len(employment_statuses)]
        ensure(
            PersonEmployment,
            {"person": person, "company": previous_company, "source_reference": f"DEMO-PRES-HISTORY-{index:04d}"},
            {
                "personnel_code": f"HIST-{index:04d}",
                "job_title": "سمت پیشین ثبت‌شده در تاریخچه",
                "valid_from": start_date - timedelta(days=900),
                "valid_until": start_date - timedelta(days=100),
                "status": status,
                "created_by": head,
                "approved_by": head,
            },
            verify_fields=("status", "valid_from", "valid_until"),
        )

    # Company-declared leadership and operational titles intentionally allow
    # several concurrent positions for one person, with a historical title.
    company_titles = (
        "مدیرعامل", "عضو هیئت‌مدیره", "رئیس هیئت‌مدیره",
        "معاون منابع انسانی", "مدیر منابع انسانی", "نماینده سلامت و درمان",
        "نماینده بیمه خودرو", "مسئول بیمه اموال",
    )
    for index, company in enumerate(companies, start=1):
        person = persons_by_company[company.pk]
        for title_index, title in enumerate(company_titles, start=1):
            ensure(
                CompanyLeadershipTitle,
                {"company": company, "person": person, "title": title},
                {
                    "valid_from": start_date - timedelta(days=900) if title_index == 1 and index % 4 == 0 else start_date,
                    "valid_until": start_date - timedelta(days=100) if title_index == 1 and index % 4 == 0 else None,
                    "declared_by": company_representatives[company.pk],
                },
                verify_fields=(),
            )

    # All insurance lines have active contracts for each company. This keeps
    # every generated claim/asset/person-change within a valid contract scope.
    line_specs = (
        (InsuranceLine.HEALTH, "health"),
        (InsuranceLine.LIFE, "life"),
        (InsuranceLine.LIABILITY, "liability"),
        (InsuranceLine.FIRE, "fire"),
        (InsuranceLine.THIRD_PARTY, "third_party"),
        (InsuranceLine.BODY, "body"),
        (InsuranceLine.OTHER, "other"),
    )
    contracts_by_company_line = {}
    for company_number, company in enumerate(companies, start=1):
        insurer_for_company = insurers[(company_number - 1) % len(insurers)]
        for line, line_code in line_specs:
            code = f"DEMO-PRES-{company_number:03d}-{line_code.upper()}"
            contract = ensure(
                Contract,
                {"code": code},
                {
                    "title": f"قرارداد نمایشی {line_code} شرکت {company_number:02d}",
                    "insurer": insurer_for_company,
                    "line": line,
                    "start_date": start_date,
                    "end_date": end_date,
                    "coverage_summary": f"پوشش نمونه رشته {line_code} برای شرکت {company_number:02d}",
                    "terms": "شرایط، سقف‌ها و استثناهای ساختگی؛ فاقد اثر حقوقی.",
                    "status": Contract.Status.ACTIVE,
                    "is_active": True,
                },
                verify_fields=("insurer", "line", "start_date", "end_date"),
            )
            contract.companies.add(company)
            contracts_by_company_line[(company.pk, line)] = contract
        health_contracts[company.pk] = contracts_by_company_line[(company.pk, InsuranceLine.HEALTH)]

    # Contract lifecycle: all defined states appear in the presentation,
    # with dates and is_active kept consistent with each state.
    contract_status_examples = (
        Contract.Status.DRAFT,
        Contract.Status.PENDING_APPROVAL,
        Contract.Status.APPROVED,
        Contract.Status.ACTIVE,
        Contract.Status.EXPIRED,
        Contract.Status.TERMINATED,
        Contract.Status.REJECTED,
        Contract.Status.LEGACY_INACTIVE,
    )
    for index, status in enumerate(contract_status_examples, start=1):
        if status in {Contract.Status.EXPIRED, Contract.Status.TERMINATED, Contract.Status.LEGACY_INACTIVE}:
            start_at = today - timedelta(days=365)
            end_at = today - timedelta(days=30)
        elif status == Contract.Status.APPROVED:
            start_at = today + timedelta(days=30)
            end_at = today + timedelta(days=395)
        else:
            start_at = today
            end_at = today + timedelta(days=365)
        lifecycle_contract = ensure(
            Contract,
            {"code": f"DEMO-PRES-LIFECYCLE-{status.upper()}"},
            {
                "title": f"نمونه چرخه عمر قرارداد — {status}",
                "insurer": insurers[(index - 1) % len(insurers)],
                "line": line_specs[(index - 1) % len(line_specs)][0],
                "start_date": start_at,
                "end_date": end_at,
                "coverage_summary": "نمونه وضعیت چرخه عمر قرارداد برای پرزنتیشن.",
                "terms": "شرایط ساختگی؛ بدون اثر حقوقی یا مالی.",
                "status": status,
                "is_active": status == Contract.Status.ACTIVE,
            },
            verify_fields=("status", "start_date", "end_date", "insurer", "line"),
        )
        lifecycle_contract.companies.add(companies[(index - 1) % len(companies)])

    # A distinct contract revision for each state; every unapplied revision
    # belongs to a different contract to respect the one-open-revision rule.
    revision_statuses = list(ContractRevision.Status.values)
    revision_contracts = list(
        Contract.objects.filter(code__startswith="DEMO-PRES-").exclude(code__startswith="DEMO-PRES-LIFECYCLE-").order_by("pk")[:50]
    )
    for index, contract in enumerate(revision_contracts, start=1):
        status = revision_statuses[(index - 1) % len(revision_statuses)]
        is_termination = status == ContractRevision.Status.TERMINATED
        snapshot = {
            "code": contract.code,
            "title": contract.title,
            "insurer_id": contract.insurer_id,
            "line": contract.line,
            "start_date": contract.start_date.isoformat(),
            "end_date": contract.end_date.isoformat(),
            "coverage_summary": contract.coverage_summary,
            "terms": contract.terms,
            "company_ids": sorted(contract.companies.values_list("pk", flat=True)),
        }
        ensure(
            ContractRevision,
            {"contract": contract, "revision_number": 1},
            {
                "description": f"نسخه نمایشی شماره {index:03d} با وضعیت {status}",
                "created_by": health_specialist,
                "status": status,
                "snapshot": snapshot,
                "effective_date": today + timedelta(days=30) if status in {
                    ContractRevision.Status.APPROVED, ContractRevision.Status.TERMINATED
                } else None,
                "approved_by": admin if status in {
                    ContractRevision.Status.APPROVED, ContractRevision.Status.TERMINATED
                } else None,
                "approved_at": now if status in {
                    ContractRevision.Status.APPROVED, ContractRevision.Status.TERMINATED
                } else None,
                "is_termination": is_termination,
                "termination_reason": "نمونه فسخ با رعایت مهلت اعلام" if is_termination else "",
                "notice_date": today if is_termination else None,
            },
            verify_fields=("status", "snapshot", "is_termination"),
        )

    # The base script's initial contract remains valid for its original scope;
    # generated records use the company-specific contracts above.
    for index, (company, person) in enumerate(
        [(c, persons_by_company[c.pk]) for c in companies], start=1
    ):
        contract = health_contracts[company.pk]
        change_type = PersonChangeRequest.ChangeType.MOBILE
        requested_mobile = f"091299{index:06d}"
        current_mobile = str(person.mobile or "")
        ensure(
            PersonChangeRequest,
            {"person": person, "change_type": change_type},
            {
                "company": company,
                "contract": contract,
                "requested_by": person.user,
                "current_value": current_mobile,
                "requested_value": requested_mobile,
                "reason": f"درخواست نمایشی اصلاح شماره همراه؛ سناریو {index:03d} برای بررسی گردش کار.",
                "status": list(PersonChangeRequest.Status.values)[(index - 1) % len(PersonChangeRequest.Status.values)],
                "approved_by": head if index % len(PersonChangeRequest.Status.values) == 4 else None,
                "approved_at": now if index % len(PersonChangeRequest.Status.values) == 4 else None,
                "rejected_by": head if index % len(PersonChangeRequest.Status.values) == 5 else None,
                "rejected_at": now if index % len(PersonChangeRequest.Status.values) == 5 else None,
            },
            verify_fields=("company", "contract", "requested_by", "current_value", "requested_value", "reason"),
        )

    # Service-request coverage is deliberately larger than the set of request
    # kinds. Each case starts through the production workflow service.
    from workflow.services import resolve_initial_assignee, start_workflow

    def start_case(obj, code, actor, note):
        content_type = ContentType.objects.get_for_model(obj, for_concrete_model=False)
        if WorkflowCase.objects.filter(
            definition__code=code,
            definition__is_active=True,
            content_type=content_type,
            object_id=str(obj.pk),
        ).exists():
            return
        definition = WorkflowDefinition.objects.filter(code=code, is_active=True).order_by("-version").first()
        if definition is None:
            raise CommandError(f"Missing active workflow definition for demo scenario: {code}")
        assignee, delegation = resolve_initial_assignee(definition=definition, obj=obj, return_delegation=True)
        start_workflow(
            obj=obj,
            code=code,
            actor=actor,
            assignee=delegation.delegate_to if delegation else assignee,
            delegation=delegation,
            note=note,
        )

    demo_requests = list(ServiceRequest.objects.filter(reference__startswith="DEMO-PRES-REQ").order_by("pk"))
    request_kinds = list(ServiceRequest.Kind.values)
    while ServiceRequest.objects.count() < MINIMUM_PER_MODEL:
        index = ServiceRequest.objects.count() + 1
        company = companies[(index - 1) % len(companies)]
        person = persons_by_company[company.pk]
        submitter = company_representatives[company.pk]
        kind = request_kinds[(index - 1) % len(request_kinds)]
        item = ensure(
            ServiceRequest,
            {"reference": f"DEMO-PRES-REQ-{index:04d}"},
            {
                "kind": kind,
                "submitted_by": submitter,
                "person": person,
                "company": company,
                "title": f"درخواست نمایشی {index:04d} — {dict(ServiceRequest.Kind.choices)[kind]}",
                "description": "سناریوی ساختگی برای نمایش ثبت، ارجاع، پیگیری و ثبت نتیجه.",
                "status": ServiceRequest.Status.SUBMITTED,
                "assigned_to": None,
                "is_confidential": kind == ServiceRequest.Kind.MEDICAL_ASSISTANCE,
            },
            verify_fields=("kind", "submitted_by", "person", "company", "is_confidential"),
        )
        demo_requests.append(item)
        start_case(item, kind, submitter, f"شروع گردش کار نمایشی درخواست {item.reference}")

    # Fifty active, versioned workflow definitions with two steps and explicit
    # approval/closure transitions. The first definitions are the real domain
    # workflows; these additional definitions expose the engine's capabilities.
    workflow_roles = list(RoleAssignment.Role.values)
    workflow_index = 1
    while WorkflowDefinition.objects.count() < MINIMUM_PER_MODEL:
        code = f"presentation-showcase-{workflow_index:03d}"
        if not WorkflowDefinition.objects.filter(code=code, version=1).exists():
            role = workflow_roles[(workflow_index - 1) % len(workflow_roles)]
            definition = WorkflowDefinition.objects.create(
                code=code,
                title=f"گردش نمایشی پیشرفته {workflow_index:03d}",
                version=1,
                created_by=admin,
                description="تعریف نمونه برای نمایش نقش مجاز، مرحله آغازین، تصمیم، بازگشت‌پذیری و بستن پرونده.",
            )
            pending = WorkflowStep.objects.create(
                definition=definition,
                code="pending",
                title="در انتظار اقدام",
                order=1,
                allowed_roles=[role],
                is_initial=True,
                sla_minutes=480,
                allow_return=True,
            )
            approved = WorkflowStep.objects.create(
                definition=definition,
                code="approved",
                title="تأییدشده",
                order=2,
                allowed_roles=[role],
                is_terminal=False,
                allow_return=True,
            )
            WorkflowTransition.objects.create(
                definition=definition,
                source_step=pending,
                target_step=approved,
                action_code="approve",
                title="تأیید",
                allowed_roles=[role],
                recipient_roles=[role],
                requires_note=True,
            )
            WorkflowTransition.objects.create(
                definition=definition,
                source_step=approved,
                target_step=None,
                action_code="close",
                title="بستن پرونده",
                allowed_roles=[role],
                recipient_roles=[],
                closes_case=True,
                requires_note=True,
            )
            definition.approved_by = admin
            definition.is_active = True
            definition.save()
        workflow_index += 1

    # Build 50 distinct vehicle policy files and vehicle details; the other
    # asset types are already represented by the base fixture archetypes.
    vehicle_assets = []
    for index, company in enumerate(companies, start=1):
        contract = contracts_by_company_line[(company.pk, InsuranceLine.THIRD_PARTY)]
        asset = ensure(
            InsuredAsset,
            {"asset_code": f"DEMO-PRES-VEH-{index:04d}"},
            {
                "name": f"خودروی سازمانی نمایشی {index:03d}",
                "asset_type": InsuredAsset.Type.VEHICLE,
                "company": company,
                "person": None,
                "identifier": f"DEMO-PLATE-REF-{index:04d}",
                "location": f"پارکینگ شرکت {index:02d}",
                "insured_value": 850000000 + index * 1250000,
                "insurer": contract.insurer,
                "contract": contract,
                "policy_number": f"DEMO-PRES-POL-{index:04d}",
                "policy_start": today - timedelta(days=30),
                "policy_end": today + timedelta(days=335),
                "is_active": True,
                "notes": "دارایی ساختگی برای نمایش تفکیک خودرو، شرکت، بیمه‌گر و بیمه‌نامه.",
                "created_by": motor_specialist,
            },
            verify_fields=("name", "asset_type", "company", "contract", "policy_number"),
        )
        vehicle_assets.append(asset)
        ensure(
            Vehicle,
            {"asset": asset},
            {
                "plate_number": f"ایران 11-{index:02d}-{100 + index} الف",
                "vin": f"DEMO-VIN-{index:08d}",
                "engine_number": f"DEMO-ENG-{index:08d}",
                "make": "سازنده نمایشی",
                "model_name": ("سواری", "وانت", "کامیون", "مینی‌بوس", "خدماتی")[index % 5],
                "model_year": 1400 + index % 6,
            },
            verify_fields=("plate_number", "vin", "model_name"),
        )

    # A minimum of 50 calendars and 50 serial-date counters make SLA and
    # correspondence numbering demonstrations visible across time windows.
    base_calendar, _ = BusinessCalendar.objects.get_or_create(
        code="demo-iran-calendar",
        defaults={
            "title": "تقویم کاری نمونه مجموعه",
            "timezone_name": "Asia/Tehran",
            "working_weekdays": [5, 6, 0, 1, 2, 3],
            "start_time": datetime.strptime("08:00", "%H:%M").time(),
            "end_time": datetime.strptime("16:00", "%H:%M").time(),
            "is_active": True,
        },
    )
    while BusinessCalendar.objects.count() < MINIMUM_PER_MODEL:
        index = BusinessCalendar.objects.count() + 1
        ensure(
            BusinessCalendar,
            {"code": f"demo-iran-calendar-{index:03d}"},
            {
                "title": f"تقویم کاری نمایشی {index:03d}",
                "timezone_name": "Asia/Tehran",
                "working_weekdays": [5, 6, 0, 1, 2, 3],
                "start_time": datetime.strptime("08:00", "%H:%M").time(),
                "end_time": datetime.strptime("16:00", "%H:%M").time(),
                "is_active": True,
            },
            verify_fields=(),
        )

    # Create 50 incoming/outgoing/internal correspondence records using the
    # real central serial-number service (one counter for every direction).
    from correspondence.services import next_internal_number
    corr_rows = list(Correspondence.objects.filter(external_reference__startswith="DEMO-PRES-CORR").order_by("pk"))
    channels = list(Correspondence.Channel.values)
    directions = list(Correspondence.Direction.values)
    followups = list(Correspondence.FollowUp.values)
    while Correspondence.objects.count() < MINIMUM_PER_MODEL:
        index = Correspondence.objects.count() + 1
        company = companies[(index - 1) % len(companies)]
        contract = health_contracts[company.pk]
        occurred_at = timezone.make_aware(datetime.combine(today - timedelta(days=index), datetime.min.time()))
        number = next_internal_number(occurred_at)
        direction = directions[(index - 1) % len(directions)]
        channel = channels[(index - 1) % len(channels)]
        follow_up = followups[(index - 1) % len(followups)]
        item = ensure(
            Correspondence,
            {"internal_number": number},
            {
                "subject": f"مکاتبه نمایشی {index:04d}",
                "channel": channel,
                "direction": direction,
                "company": company,
                "insurer": contract.insurer,
                "contract": contract,
                "external_reference": f"DEMO-PRES-CORR-{index:04d}",
                "summary": "مکاتبه ساختگی برای نمایش ثبت ورودی، خروجی، داخلی و پیگیری.",
                "occurred_at": occurred_at,
                "follow_up_due": today + timedelta(days=index % 20),
                "follow_up_status": follow_up,
                "assigned_to": health_specialist,
                "is_confidential": index % 7 == 0,
                "created_by": head,
            },
            verify_fields=("external_reference", "direction", "channel", "company", "insurer", "contract"),
        )
        corr_rows.append(item)
        ensure(
            CorrespondenceEvent,
            {"correspondence": item, "event_type": CorrespondenceEvent.EventType.CREATED, "summary": f"ثبت مکاتبه نمایشی {index:04d}"},
            {"actor": head, "metadata": {"fixture": "DEMO-PRESENTATION", "number": item.internal_number}},
        )
        follow_event = list(CorrespondenceEvent.EventType.values)[index % len(CorrespondenceEvent.EventType.values)]
        ensure(
            CorrespondenceEvent,
            {"correspondence": item, "event_type": follow_event, "summary": f"پیگیری مکاتبه نمایشی {index:04d}"},
            {"actor": health_specialist, "metadata": {"fixture": "DEMO-PRESENTATION", "step": index}},
        )

    # The same correspondence list is linked to independent claims for a
    # realistic traceable document/claim/letter timeline.
    claim_type = ContentType.objects.get_for_model(Claim, for_concrete_model=False)
    claims_for_link = list(Claim.objects.order_by("pk"))
    for index, correspondence in enumerate(Correspondence.objects.order_by("pk")[:MINIMUM_PER_MODEL], start=1):
        claim = claims_for_link[(index - 1) % len(claims_for_link)]
        ensure(
            CorrespondenceLink,
            {"correspondence": correspondence, "content_type": claim_type, "object_id": str(claim.pk)},
            {"created_by": head},
            verify_fields=("created_by",),
        )

    # Additional workflow requests above normally provide at least 50 cases.
    # If a domain configuration has no workflow for a kind, do not fabricate a
    # case; fail with a clear contract error rather than write an invalid record.
    if WorkflowCase.objects.count() < MINIMUM_PER_MODEL:
        raise CommandError(
            f"Only {WorkflowCase.objects.count()} workflow cases were created; "
            f"the presentation gate requires {MINIMUM_PER_MODEL}. Check active request workflows."
        )

    # Create a full set of import batches with representative statuses and
    # synthetic XLSX files. The files are not processed automatically.
    while ImportBatch.objects.count() < MINIMUM_PER_MODEL:
        index = ImportBatch.objects.count() + 1
        status = list(ImportBatch.Status.values)[(index - 1) % len(ImportBatch.Status.values)]
        category = ("claims", "people_roster", "contracts")[(index - 1) % 3]
        actor = company_representatives[companies[(index - 1) % len(companies)].pk] if category == "people_roster" else insurer_representatives[insurers[(index - 1) % len(insurers)].pk] if category == "claims" else health_specialist
        batch = ensure(
            ImportBatch,
            {"batch_number": f"DEMO-PRES-IMPORT-{index:04d}"},
            {
                "source_type": category,
                "file": _sample_xlsx(f"demo-presentation-{category}-{index:04d}.xlsx", category, index),
                "uploaded_by": actor,
                "status": status,
                "total_rows": 50 + index,
                "valid_rows": 45,
                "invalid_rows": 5,
                "result_report": "گزارش نمایشی اعتبارسنجی؛ هیچ داده‌ای به صورت خودکار اعمال نشده است.",
                "preview_data": [{"row": 2, "status": "valid"}, {"row": 3, "status": "invalid", "error": "نمونه خطا"}],
                "column_mapping": {"national_id": "A", "service_type": "C", "amount": "D"},
                "reviewed_by": head if status == ImportBatch.Status.PROCESSED else None,
                "reviewed_at": now if status == ImportBatch.Status.PROCESSED else None,
                "review_note": "تأیید نمونه" if status == ImportBatch.Status.PROCESSED else "",
            },
            verify_fields=("source_type", "uploaded_by", "status", "total_rows", "valid_rows", "invalid_rows"),
        )

    # Create 50 task work items and append-only timelines.
    priorities = list(InternalTask.Priority.values)
    task_statuses = list(InternalTask.Status.values)
    task_rows = list(InternalTask.objects.order_by("pk"))
    while InternalTask.objects.count() < MINIMUM_PER_MODEL:
        index = InternalTask.objects.count() + 1
        actor = health_lead if index % 2 else health_specialist
        task = ensure(
            InternalTask,
            {"title": f"وظیفه ارائه {index:04d}"},
            {
                "description": f"وظیفه نمایشی {index:04d} برای آزمون مهلت، اولویت، مسئول و وضعیت.",
                "created_by": actor,
                "priority": priorities[(index - 1) % len(priorities)],
                "status": task_statuses[(index - 1) % len(task_statuses)],
                "due_at": now + timedelta(days=(index % 15) - 7),
                "related_request": ServiceRequest.objects.order_by("pk")[(index - 1) % ServiceRequest.objects.count()],
            },
            verify_fields=(),
        )
        assignee = (health_lead, health_specialist, fire_specialist, motor_specialist)[index % 4]
        task.assignees.add(assignee)
        ensure(
            TaskEvent,
            {"task": task, "event_type": TaskEvent.EventType.CREATED, "note": f"ایجاد وظیفه نمایشی {index:04d}"},
            {"actor": actor, "from_value": "", "to_value": task.status, "occurred_at": now - timedelta(minutes=index)},
        )
        event_type = list(TaskEvent.EventType.values)[index % len(TaskEvent.EventType.values)]
        ensure(
            TaskEvent,
            {"task": task, "event_type": event_type, "note": f"اقدام روی وظیفه نمایشی {index:04d}"},
            {"actor": assignee, "from_value": "", "to_value": task.status, "occurred_at": now - timedelta(minutes=index - 1)},
        )

    # Fifty immutable delegation records and their audit events, scoped to
    # actual company representatives. Existing manager/admin permissions are
    # used only as grantors; no fictitious staff identity is introduced.
    delegation_reps = list(company_representatives.values())
    while WorkDelegation.objects.count() < MINIMUM_PER_MODEL:
        index = WorkDelegation.objects.count() + 1
        company = companies[(index - 1) % len(companies)]
        delegate = company_representatives[company.pk]
        delegation, _ = record(
            WorkDelegation,
            {
                "workflow_code": "service_request",
                "item_type": "medical_assistance",
                "delegate_role": RoleAssignment.Role.SUBSIDIARY_REP,
                "delegate_to": delegate,
                "granted_by": head,
                "company": company,
                "insurer": None,
                "line_code": "health",
            },
            {
                "reason": f"تفویض نمایشی شماره {index:04d}، محدود به شرکت، فرآیند و رشته درمان.",
                "status": WorkDelegation.Status.ACTIVE if index % 4 else WorkDelegation.Status.SUSPENDED,
                "valid_from": today - timedelta(days=5),
                "valid_until": today + timedelta(days=30),
                "revocation_reason": "",
            },
            verify_fields=("reason", "delegate_to", "company", "line_code"),
        )
        ensure(
            DelegationEvent,
            {"delegation": delegation, "event_type": DelegationEvent.EventType.CREATED, "summary": f"ایجاد تفویض نمایشی {index:04d}"},
            {"actor": head, "metadata": {"fixture": "DEMO-PRESENTATION", "company_id": company.pk}},
        )
        if delegation.status == WorkDelegation.Status.SUSPENDED:
            ensure(
                DelegationEvent,
                {"delegation": delegation, "event_type": DelegationEvent.EventType.SUSPENDED, "summary": f"تعلیق تفویض نمایشی {index:04d}"},
                {"actor": head, "metadata": {"fixture": "DEMO-PRESENTATION"}},
            )

    # Expand the append-only records and lookup tables that are naturally
    # high-volume. The model's own save validation remains enabled.
    generic_labels = (
        "accounts.usernotification",
        "announcements.announcement",
        "assets.assetvaluation",
        "assets.assetpolicyperiod",
        "assets.assetpolicyendorsement",
        "auditlog.auditevent",
        "claims.claim",
        "claims.claimpayment",
        "claims.claimobjection",
        "correspondence.correspondenceevent",
        "delegations.delegationevent",
        "documents.documentaccessevent",
        "tasks.taskevent",
        "workflow.workflowevent",
        "workflow.businesscalendar",
        "workflow.calendarholiday",
    )
    for label in generic_labels:
        model = apps.get_model(label)
        sources = None
        if label == "claims.claimpayment":
            sources = list(model._base_manager.filter(entry_type=ClaimPayment.EntryType.PAYMENT).order_by("pk"))
        if label == "workflow.workflowevent":
            sources = list(model._base_manager.order_by("pk"))
        _clone_until_minimum(
            model,
            target=MINIMUM_PER_MODEL,
            created_counts=created_counts,
            preferred_sources=sources,
        )

    # Ensure 50 documents (and therefore 50+ versions) using the secure
    # document service so checksums and initial version rows are generated.
    from documents.services import create_document, record_document_access
    from documents.models import DocumentRecord, DocumentVersion, DocumentLink
    from django.contrib.contenttypes.models import ContentType

    while DocumentRecord.objects.count() < MINIMUM_PER_MODEL:
        index = DocumentRecord.objects.count() + 1
        company = companies[(index - 1) % len(companies)]
        person = persons_by_company[company.pk]
        security = list(DocumentRecord.SecurityLevel.values)[(index - 1) % len(DocumentRecord.SecurityLevel.values)]
        medical = security == DocumentRecord.SecurityLevel.VERY_CONFIDENTIAL
        doc = create_document(
            title=f"پرونده سند نمایشی {index:04d}",
            category=("قرارداد", "پرسنلی", "مکاتبه", "خسارت", "دارایی")[index % 5],
            upload=ContentFile(b"%PDF-1.4\nSynthetic office_kmc presentation document\n%%EOF", name=f"demo-presentation-doc-{index:04d}.pdf"),
            uploaded_by=health_specialist,
            company=company,
            person=person,
            security_level=security,
            is_medical=medical,
            change_reason="نسخه اولیه سند نمایشی",
        )
        if index % 5 == 0:
            from documents.services import add_document_version
            add_document_version(
                document_id=doc.pk,
                upload=ContentFile(b"%PDF-1.4\nSynthetic revised presentation document\n%%EOF", name=f"demo-presentation-doc-{index:04d}-v2.pdf"),
                uploaded_by=head,
                change_reason="نسخه دوم برای نمایش تاریخچه تغییرات",
            )

    document_rows = list(DocumentRecord.objects.order_by("pk"))
    claim_rows = list(Claim.objects.order_by("pk"))
    document_type = ContentType.objects.get_for_model(DocumentRecord, for_concrete_model=False)
    claim_type = ContentType.objects.get_for_model(Claim, for_concrete_model=False)
    person_type = ContentType.objects.get_for_model(Person, for_concrete_model=False)
    for index, document in enumerate(document_rows[:MINIMUM_PER_MODEL], start=1):
        target = claim_rows[(index - 1) % len(claim_rows)]
        ensure(
            DocumentLink,
            {"document": document, "content_type": claim_type, "object_id": str(target.pk)},
            {"created_by": health_specialist},
            verify_fields=("created_by",),
        )
        version = document.current_version
        if version:
            action = list(DocumentAccessEvent.Action.values)[(index - 1) % len(DocumentAccessEvent.Action.values)]
            if not DocumentAccessEvent.objects.filter(document=document, actor=head, action=action).exists():
                record_document_access(document=document, version=version, actor=head, action=action)

    # Coverage expansion for the remaining smaller model tables.
    for label in (
        "organizations.personchangerequest",
        "insurance.contractrevision",
    ):
        model = apps.get_model(label)
        if _count(model) >= MINIMUM_PER_MODEL:
            continue
        _clone_until_minimum(model, target=MINIMUM_PER_MODEL, created_counts=created_counts)

    # Ensure calendars have enough dated exceptions, since holidays are unique
    # by calendar/date and should not be cloned with the same date.
    while CalendarHoliday.objects.count() < MINIMUM_PER_MODEL:
        index = CalendarHoliday.objects.count() + 1
        ensure(
            CalendarHoliday,
            {"calendar": base_calendar, "date": today + timedelta(days=60 + index)},
            {
                "title": f"تعطیلی/استثنای نمایشی {index:04d}",
                "is_working_override": index % 5 == 0,
            },
            verify_fields=(),
        )

    # Ensure audit rows are diverse and explicitly synthetic.
    while AuditEvent.objects.count() < MINIMUM_PER_MODEL:
        index = AuditEvent.objects.count() + 1
        ensure(
            AuditEvent,
            {
                "action": f"presentation_demo_event_{index:04d}",
                "object_type": "PresentationScenario",
                "object_id": str(index),
                "summary": f"رویداد ممیزی نمایشی {index:04d}",
            },
            {
                "actor": head,
                "before_data": {"fixture": True},
                "after_data": {"fixture": "DEMO-PRESENTATION", "scenario": index},
                "metadata": {"synthetic": True, "environment": "presentation"},
            },
        )

    # Final, exhaustive gate: every concrete model named in the manifest must
    # have at least 50 linked examples. No green summary is printed otherwise.
    from core.management.commands.demo_seed_support import EXPECTED_MODEL_LABELS

    coverage = {}
    for label in EXPECTED_MODEL_LABELS:
        model = apps.get_model(label)
        coverage[label] = _count(model)
    missing = {label: count for label, count in coverage.items() if count < MINIMUM_PER_MODEL}
    if missing:
        detail = ", ".join(f"{label}={count}" for label, count in sorted(missing.items()))
        raise CommandError(
            f"Presentation data is incomplete. Each of the {len(EXPECTED_MODEL_LABELS)} models requires "
            f"at least {MINIMUM_PER_MODEL} records. Below target: {detail}"
        )

    return {
        "model_coverage": len(coverage),
        "minimum_per_model": MINIMUM_PER_MODEL,
        "model_counts": coverage,
        "total_model_rows": sum(coverage.values()),
        "companies": Company.objects.count(),
        "insurers": Insurer.objects.count(),
        "company_representatives": len(company_representatives),
        "insurer_representatives": len(insurer_representatives),
        "service_requests": ServiceRequest.objects.count(),
        "workflow_cases": WorkflowCase.objects.count(),
        "claims": Claim.objects.count(),
        "assets": InsuredAsset.objects.count(),
        "documents": DocumentRecord.objects.count(),
        "correspondence": Correspondence.objects.count(),
        "delegations": WorkDelegation.objects.count(),
    }
