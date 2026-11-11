"""Profile-driven, preview-first Excel imports.

Uploaded rows are validated into a staged ImportBatch. Domain records are only
created after an independent reviewer confirms the batch.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import secrets

import jdatetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, models, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from accounts.access import (
    company_ids_for, has_global_access, has_role, insurer_ids_for, line_codes_for,
)
from accounts.models import RoleAssignment
from assets.models import AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle
from auditlog.services import record_event
from claims.models import Claim
from claims.services import record_imported_payment
from core.uploads import validate_uploaded_file
from insurance.models import Contract, ContractRevision, InsuranceLine, Insurer
from organizations.models import Company, Person, PersonEmployment, normalize_national_id
from workflow.models import WorkflowDefinition
from workflow.services import resolve_initial_assignee, start_workflow

from .forms import FlexibleExcelImportForm
from .models import ImportBatch
from .profiles import PROFILES, get_profile


MAX_IMPORT_ROWS = 10000
MAX_PREVIEW_ROWS = 30
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _column_index(value):
    result = 0
    for char in value:
        result = result * 26 + ord(char) - 64
    return result - 1


def _text(value):
    return "" if value is None else str(value).strip()


def _parse_date(value, row_number, field):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value).translate(PERSIAN_DIGITS)
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            parsed = datetime.strptime(raw[:10], pattern).date()
            if 1300 <= parsed.year <= 1499:
                return jdatetime.date(parsed.year, parsed.month, parsed.day).togregorian()
            return parsed
        except (TypeError, ValueError):
            pass
    raise ValueError(f"ردیف {row_number}: تاریخ «{field}» معتبر نیست؛ YYYY-MM-DD یا تاریخ شمسی وارد کنید.")


def _parse_amount(value, row_number, field):
    if value in (None, ""):
        return Decimal("0")
    raw = _text(value).translate(PERSIAN_DIGITS).replace(",", "").replace("٬", "").replace("٫", ".")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise ValueError(f"ردیف {row_number}: مبلغ «{field}» عددی نیست.")
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"ردیف {row_number}: مبلغ «{field}» باید عددی معتبر و نامنفی باشد.")
    if max(0, len(amount.as_tuple().digits) + amount.as_tuple().exponent) > 14 or max(0, -amount.as_tuple().exponent) > 2:
        raise ValueError(f"ردیف {row_number}: مبلغ «{field}» حداکثر ۱۴ رقم صحیح و ۲ رقم اعشار می‌پذیرد.")
    return amount


def _staff(user):
    return has_global_access(user) or has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)


def _profile_allowed(user, code):
    if code == "people_roster":
        specialist_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        return (
            has_global_access(user)
            or ("health" in specialist_lines or "*" in specialist_lines)
            or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        )
    if code == "claims":
        return (
            has_global_access(user)
            or has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST)
            or has_role(user, RoleAssignment.Role.INSURER_REP)
        )
    if code == "contracts":
        return _staff(user)
    if code == "assets":
        return _staff(user)
    return False


def _can_review(user, code):
    if code == "contracts":
        return has_global_access(user)
    if code == "people_roster":
        specialist_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        return has_global_access(user) or ("health" in specialist_lines or "*" in specialist_lines)
    if code == "claims":
        return _staff(user)
    if code == "assets":
        return has_global_access(user)
    return False

def _can_review_batch(user, batch):
    if not _can_review(user, batch.source_type):
        return False
    if has_global_access(user):
        return True
    if batch.source_type != "claims":
        return True
    permitted_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
    if "*" in permitted_lines:
        return True
    if not isinstance(batch.preview_data, list) or not batch.preview_data:
        return False
    if any(
        not isinstance(row, dict) or not row.get("contract_id")
        for row in batch.preview_data
    ):
        return False
    contract_ids = {row["contract_id"] for row in batch.preview_data}
    contracts = Contract.objects.filter(pk__in=contract_ids, is_active=True, status=Contract.Status.ACTIVE)
    return contracts.count() == len(contract_ids) and set(
        contracts.values_list("line", flat=True)
    ).issubset(permitted_lines)


def _company_for_row(user, raw_code, row_number):
    representative_ids = company_ids_for(user, role=RoleAssignment.Role.SUBSIDIARY_REP)
    code = _text(raw_code)
    if representative_ids:
        if len(representative_ids) == 1:
            company_id = next(iter(representative_ids))
            company = Company.objects.filter(pk=company_id, is_active=True).first()
            if not company:
                raise ValueError(f"ردیف {row_number}: شرکت فعال نماینده پیدا نشد.")
            if code and code != company.code:
                raise ValueError(f"ردیف {row_number}: کد شرکت فایل خارج از محدوده انتصاب شماست.")
            return company
        if not code:
            raise ValueError(f"ردیف {row_number}: حساب شما به چند شرکت منتسب است؛ ستون company_code را تکمیل کنید.")
        company = Company.objects.filter(code=code, is_active=True).first()
        if not company or company.pk not in representative_ids:
            raise ValueError(f"ردیف {row_number}: شرکت انتخاب‌شده در محدوده انتصاب شما نیست.")
        return company
    if not has_global_access(user) and not has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        raise PermissionDenied
    if not code:
        raise ValueError(f"ردیف {row_number}: برای ورود سازمانی، ستون company_code الزامی است.")
    company = Company.objects.filter(code=code, is_active=True).first()
    if not company:
        raise ValueError(f"ردیف {row_number}: شرکت فعال با کد {code} یافت نشد.")
    return company


def _mapped_rows(upload, mapping, header_row):
    workbook = load_workbook(upload, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        headings = next(sheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True), None)
        if not headings or not any(value not in (None, "") for value in headings):
            raise ValueError("ردیف عنوان ستون‌ها خالی است؛ شماره ردیف سرستون را اصلاح کنید.")
        indexes = {key: _column_index(letter) for key, letter in mapping.items()}
        count = 0
        for row_number, row in enumerate(
            sheet.iter_rows(min_row=header_row + 1, values_only=True),
            start=header_row + 1,
        ):
            if not any(value not in (None, "") for value in row):
                continue
            count += 1
            if count > MAX_IMPORT_ROWS:
                raise ValueError(f"حداکثر تعداد ردیف داده در هر فایل {MAX_IMPORT_ROWS:,} است.")
            yield row_number, {
                key: row[index] if index < len(row) else None
                for key, index in indexes.items()
            }
    finally:
        workbook.close()


def _preview_people(user, mapped_rows):
    from organizations.models import Person

    valid, errors, seen = [], [], set()
    staged_employees = {}
    for row_number, raw in list(mapped_rows):
        birth_date = None
        try:
            action = _text(raw.get("action")).lower()
            action = {
                "افزودن": "add_employee",
                "افزودن_کارمند": "add_employee",
                "افزودن_وابسته": "add_dependent",
                "خاتمه": "end_employment",
                "خاتمه_همکاری": "end_employment",
            }.get(action, action)
            if action not in {"add_employee", "add_dependent", "end_employment"}:
                raise ValueError(f"ردیف {row_number}: عملیات باید add_employee، add_dependent یا end_employment باشد.")
            national_id = normalize_national_id(raw.get("national_id"))
            if len(national_id) != 10:
                raise ValueError(f"ردیف {row_number}: کد ملی باید دقیقاً ۱۰ رقم باشد.")
            if national_id in seen:
                raise ValueError(f"ردیف {row_number}: کد ملی در همین فایل تکراری است.")
            company = _company_for_row(user, raw.get("company_code"), row_number)
            person = Person.objects.filter(national_id=national_id).first()
            employment_history = PersonEmployment.objects.filter(person=person) if person else PersonEmployment.objects.none()
            active_employment = employment_history.filter(status=PersonEmployment.Status.ACTIVE).first()

            if action == "add_employee":
                if not _text(raw.get("first_name")) or not _text(raw.get("last_name")):
                    raise ValueError(f"ردیف {row_number}: نام و نام خانوادگی برای افزودن کارمند الزامی است.")
                birth_date = _parse_date(raw.get("birth_date"), row_number, "birth_date")
                if not birth_date or birth_date > timezone.localdate():
                    raise ValueError(f"ردیف {row_number}: تاریخ تولد معتبر و غیرآینده الزامی است.")
                if active_employment:
                    raise ValueError(f"ردیف {row_number}: این شخص در حال حاضر سابقه اشتغال فعال دارد؛ افزودن مجدد مجاز نیست.")
                if person and not employment_history.exists():
                    if person.company_id == company.pk:
                        raise ValueError(f"ردیف {row_number}: این شخص قبلاً در همین شرکت ثبت شده است.")
                    raise ValueError(f"ردیف {row_number}: تغییر شرکت باید از مسیر رسمی انتقال انجام شود.")
                if person and not employment_history.filter(company=company).exists():
                    raise ValueError(f"ردیف {row_number}: انتقال یا استخدام مجدد در شرکت دیگر باید از مسیر رسمی بررسی شود.")

            elif action == "add_dependent":
                relationship = _text(raw.get("relationship")).lower()
                allowed_relationships = {
                    Person.Relationship.SPOUSE, Person.Relationship.CHILD,
                    Person.Relationship.FATHER, Person.Relationship.MOTHER,
                    Person.Relationship.OTHER,
                }
                if relationship not in allowed_relationships:
                    raise ValueError(f"ردیف {row_number}: برای فرد تحت تکفل نسبت معتبر وارد کنید.")
                employee_national_id = normalize_national_id(raw.get("employee_national_id"))
                if len(employee_national_id) != 10:
                    raise ValueError(f"ردیف {row_number}: کد ملی بیمه‌شده اصلی معتبر نیست.")
                employee = Person.objects.filter(national_id=employee_national_id, is_active=True).first()
                staged_company_id = staged_employees.get(employee_national_id)
                if not employee and staged_company_id is None:
                    raise ValueError(f"ردیف {row_number}: بیمه‌شده اصلی پیدا نشد؛ ردیف کارمند اصلی باید پیش از فرد تحت تکفل باشد.")
                if staged_company_id is not None:
                    if staged_company_id != company.pk:
                        raise ValueError(f"ردیف {row_number}: فرد تحت تکفل باید با شرکت کارمند اصلی یکسان باشد.")
                else:
                    if employee.relationship != Person.Relationship.EMPLOYEE or employee.employee_id:
                        raise ValueError(f"ردیف {row_number}: کد ملی والد باید متعلق به بیمه‌شده اصلی باشد.")
                    employee_active = PersonEmployment.objects.filter(
                        person=employee, company=company, status=PersonEmployment.Status.ACTIVE
                    ).exists()
                    if not employee_active and not (
                        employee.company_id == company.pk
                        and not PersonEmployment.objects.filter(person=employee).exists()
                    ):
                        raise ValueError(f"ردیف {row_number}: بیمه‌شده اصلی در این شرکت اشتغال فعال ندارد.")
                if person:
                    raise ValueError(f"ردیف {row_number}: کد ملی فرد تحت تکفل قبلاً ثبت شده است.")
                if not _text(raw.get("first_name")) or not _text(raw.get("last_name")):
                    raise ValueError(f"ردیف {row_number}: نام و نام خانوادگی فرد تحت تکفل الزامی است.")
                birth_date = _parse_date(raw.get("birth_date"), row_number, "birth_date")
                if not birth_date or birth_date > timezone.localdate():
                    raise ValueError(f"ردیف {row_number}: تاریخ تولد معتبر و غیرآینده الزامی است.")

            else:
                if not person:
                    raise ValueError(f"ردیف {row_number}: شخصی با این کد ملی یافت نشد.")
                active_employments = PersonEmployment.objects.filter(
                    person=person, company=company, status=PersonEmployment.Status.ACTIVE
                )
                if active_employments.count() != 1:
                    raise ValueError(
                        f"ردیف {row_number}: باید دقیقاً یک سابقه اشتغال فعال در شرکت انتخاب‌شده وجود داشته باشد."
                    )

            normalized_row = {
                "action": action,
                "national_id": national_id,
                "company_id": company.pk,
                "company_code": company.code,
                "first_name": _text(raw.get("first_name"))[:100],
                "last_name": _text(raw.get("last_name"))[:100],
                "birth_date": birth_date.isoformat() if birth_date else None,
                "personnel_code": _text(raw.get("personnel_code"))[:50],
                "mobile": _text(raw.get("mobile"))[:20],
                "iban": _text(raw.get("iban")).replace(" ", "").upper()[:34],
                "relationship": _text(raw.get("relationship")).lower(),
                "employee_national_id": normalize_national_id(raw.get("employee_national_id")),
                "source_row": row_number,
            }
            valid.append(normalized_row)
            seen.add(national_id)
            if action == "add_employee":
                staged_employees[national_id] = company.pk
        except (ValueError, ValidationError, PermissionDenied) as exc:
            errors.append(str(exc))
    return valid, errors

def _preview_claims(user, mapped_rows):
    is_insurer = has_role(user, RoleAssignment.Role.INSURER_REP) and not has_global_access(user)
    insurer_ids = insurer_ids_for(user) if is_insurer else set()
    if is_insurer and len(insurer_ids) != 1:
        raise PermissionDenied("نماینده بیمه‌گر باید دقیقاً به یک بیمه‌گر فعال منتسب باشد.")
    insurer_id = next(iter(insurer_ids)) if is_insurer else None
    valid, errors, seen = [], [], set()
    line_choices = dict(InsuranceLine.choices)
    for row_number, raw in mapped_rows:
        try:
            source_number = _text(raw.get("claim_number"))
            national_id = normalize_national_id(raw.get("national_id"))
            service_type = _text(raw.get("service_type"))
            contract_code = _text(raw.get("contract_number"))
            line_code = _text(raw.get("line_code")) or "health"
            service_date = _parse_date(raw.get("service_date"), row_number, "service_date")
            if not source_number or not national_id or not service_type or not contract_code or not service_date:
                raise ValueError(f"ردیف {row_number}: شناسه پرونده، کد ملی، نوع خدمت، شماره قرارداد و تاریخ خدمت الزامی است.")
            if len(source_number) > 120:
                raise ValueError(f"ردیف {row_number}: شماره پرونده منبع بیش از حد مجاز است.")
            if line_code not in line_choices:
                raise ValueError(f"ردیف {row_number}: کد رشته بیمه معتبر نیست.")
            if not is_insurer and not has_global_access(user) and has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
                if not has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line_code):
                    raise ValueError(f"ردیف {row_number}: رشته بیمه خارج از محدوده انتصاب شماست.")
            if source_number in seen:
                raise ValueError(f"ردیف {row_number}: شماره پرونده منبع در همین فایل تکراری است.")
            person = Person.objects.filter(national_id=national_id, is_active=True).first()
            if not person:
                raise ValueError(f"ردیف {row_number}: شخص فعال با کد ملی واردشده یافت نشد.")
            primary = person.employee if person.employee_id else person
            history = PersonEmployment.objects.filter(person=primary)
            if service_date:
                matching = history.filter(
                    models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=service_date)
                ).filter(
                    models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=service_date)
                ).order_by("-valid_from", "-pk")
                if matching.count() > 1:
                    raise ValueError(f"ردیف {row_number}: سوابق اشتغال در تاریخ خدمت هم‌پوشانی دارند.")
                employment = matching.first()
            else:
                employment = history.filter(status=PersonEmployment.Status.ACTIVE).first()
            company_id = employment.company_id if employment else None
            if not company_id and not history.exists():
                company_id = primary.company_id or person.company_id
            if not company_id:
                raise ValueError(f"ردیف {row_number}: شرکت شخص در تاریخ خدمت قابل تعیین نیست.")
            contract_qs = Contract.objects.filter(
                code=contract_code,
                line=line_code,
                companies__id=company_id,
                start_date__lte=service_date,
                end_date__gte=service_date,
                is_active=True,
                status=Contract.Status.ACTIVE,
            )
            if is_insurer:
                contract_qs = contract_qs.filter(insurer_id=insurer_id)
            if contract_qs.count() != 1:
                raise ValueError(f"ردیف {row_number}: قرارداد یکتای منطبق با شرکت، رشته و تاریخ خدمت پیدا نشد.")
            contract = contract_qs.select_related("insurer").first()
            if Claim.objects.filter(insurer=contract.insurer, source_claim_number=source_number).exists():
                raise ValueError(f"ردیف {row_number}: این شماره پرونده قبلاً از همین بیمه‌گر وارد شده است.")
            amounts = {
                key: _parse_amount(raw.get(key), row_number, key)
                for key in ("requested_amount", "assessed_amount", "payable_amount", "paid_amount")
            }
            dates = {
                key: _parse_date(raw.get(key), row_number, key)
                for key in ("registered_date", "source_registered_date", "payment_date")
            }
            if amounts["assessed_amount"] > amounts["requested_amount"]:
                raise ValueError(f"ردیف {row_number}: مبلغ ارزیابی‌شده نمی‌تواند از مبلغ درخواستی بیشتر باشد.")
            if amounts["assessed_amount"] and amounts["payable_amount"] > amounts["assessed_amount"]:
                raise ValueError(f"ردیف {row_number}: مبلغ قابل پرداخت نمی‌تواند از مبلغ ارزیابی‌شده بیشتر باشد.")
            if amounts["paid_amount"] > amounts["payable_amount"]:
                raise ValueError(f"ردیف {row_number}: مبلغ پرداخت‌شده از مبلغ قابل پرداخت بیشتر است.")
            if dates["payment_date"] and not amounts["paid_amount"]:
                raise ValueError(f"ردیف {row_number}: تاریخ پرداخت بدون مبلغ پرداخت‌شده مجاز نیست.")
            duplicate_raw = _text(raw.get("source_duplicate_status")).lower()
            duplicate = duplicate_raw in {"1", "yes", "true", "duplicate", "declared_duplicate", "تکراری"}
            duplicate_reference = _text(raw.get("source_duplicate_reference"))
            if duplicate and not is_insurer:
                raise ValueError(f"ردیف {row_number}: اعلام تکراری بودن فقط توسط نماینده بیمه‌گر پذیرفته می‌شود.")
            if duplicate and not duplicate_reference:
                raise ValueError(f"ردیف {row_number}: برای اعلام تکراری بودن، شماره پرونده اصلی الزامی است.")
            valid.append({
                "claim_number": "IMP-" + secrets.token_hex(12).upper(),
                "source_claim_number": source_number,
                "national_id": national_id,
                "person_id": person.pk,
                "primary_insured_id": primary.pk,
                "company_snapshot_id": company_id,
                "service_type": service_type[:120],
                "service_date": service_date.isoformat(),
                "registered_date": (dates["registered_date"] or timezone.localdate()).isoformat(),
                "source_registered_date": dates["source_registered_date"].isoformat() if dates["source_registered_date"] else None,
                "contract_id": contract.pk,
                "contract_number_snapshot": contract.code,
                "insurer_id": contract.insurer_id,
                "source_duplicate_status": Claim.DuplicateStatus.DECLARED_DUPLICATE if duplicate else Claim.DuplicateStatus.NOT_DECLARED,
                "source_duplicate_reference": duplicate_reference[:120],
                "source_duplicate_note": _text(raw.get("source_duplicate_note"))[:4000],
                "source_duplicate_reported_at": timezone.now().isoformat() if duplicate else None,
                "source_duplicate_reported_by_id": user.pk if duplicate else None,
                **{key: str(value) for key, value in amounts.items()},
                **{key: value.isoformat() if value else None for key, value in dates.items()},
                "source_reference": "Excel import",
                "imported_at": timezone.now().isoformat(),
                "_row": row_number,
            })
            seen.add(source_number)
        except (ValueError, ValidationError, PermissionDenied) as exc:
            errors.append(str(exc))
    return valid, errors


def _preview_assets(user, mapped_rows):
    valid, errors, seen_assets, seen_policies = [], [], set(), set()
    asset_types = dict(InsuredAsset.Type.choices)
    owner_types = {"company", "person"}
    valuation_methods = {
        AssetValuation.Method.FORMAL,
        AssetValuation.Method.EXPERT,
        AssetValuation.Method.DECLARED,
    }
    today = timezone.localdate()

    for row_number, raw in mapped_rows:
        try:
            asset_code = _text(raw.get("asset_code"))
            name = _text(raw.get("name"))
            asset_type = _text(raw.get("asset_type")).lower()
            owner_type = _text(raw.get("owner_type")).lower()
            contract_code = _text(raw.get("contract_number"))
            policy_number = _text(raw.get("policy_number"))
            if not all((asset_code, name, asset_type, owner_type, contract_code, policy_number)):
                raise ValueError(f"ردیف {row_number}: کد و عنوان دارایی، نوع مالک، نوع دارایی، شماره قرارداد و شماره بیمه‌نامه الزامی است.")
            if len(asset_code) > 80 or len(name) > 250 or len(policy_number) > 100:
                raise ValueError(f"ردیف {row_number}: طول کد/عنوان دارایی یا شماره بیمه‌نامه بیش از حد مجاز است.")
            if asset_type not in asset_types:
                raise ValueError(f"ردیف {row_number}: نوع دارایی معتبر نیست.")
            if owner_type not in owner_types:
                raise ValueError(f"ردیف {row_number}: مالک باید company یا person باشد.")
            if asset_code in seen_assets or InsuredAsset.objects.filter(asset_code=asset_code).exists():
                raise ValueError(f"ردیف {row_number}: کد دارایی تکراری است.")
            if policy_number in seen_policies or AssetPolicyPeriod.objects.filter(policy_number=policy_number).exists():
                raise ValueError(f"ردیف {row_number}: شماره بیمه‌نامه تکراری است.")

            contract = Contract.objects.filter(
                code=contract_code,
                status=Contract.Status.ACTIVE,
                is_active=True,
            ).select_related("insurer").first()
            if not contract:
                raise ValueError(f"ردیف {row_number}: قرارداد فعال با شماره {contract_code} یافت نشد.")
            if not has_global_access(user) and not has_role(
                user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=contract.line
            ):
                raise ValueError(f"ردیف {row_number}: رشته قرارداد خارج از انتصاب فعال شماست.")

            company = None
            person = None
            if owner_type == "company":
                company_code = _text(raw.get("company_code"))
                if not company_code:
                    raise ValueError(f"ردیف {row_number}: کد شرکت مالک الزامی است.")
                company = Company.objects.filter(code=company_code, is_active=True).first()
                if not company:
                    raise ValueError(f"ردیف {row_number}: شرکت فعال با این کد پیدا نشد.")
                if _text(raw.get("owner_national_id")):
                    raise ValueError(f"ردیف {row_number}: برای دارایی شرکتی، کد ملی مالک باید خالی باشد.")
                company_id = company.pk
            else:
                national_id = normalize_national_id(raw.get("owner_national_id"))
                if len(national_id) != 10:
                    raise ValueError(f"ردیف {row_number}: برای دارایی شخصی، کد ملی مالک الزامی و باید ۱۰ رقمی باشد.")
                if _text(raw.get("company_code")):
                    raise ValueError(f"ردیف {row_number}: برای دارایی شخصی، ستون کد شرکت باید خالی باشد.")
                person = Person.objects.filter(national_id=national_id, is_active=True).first()
                if not person:
                    raise ValueError(f"ردیف {row_number}: مالک شخصی فعال با این کد ملی پیدا نشد.")
                primary = person.employee if person.employee_id else person
                history = PersonEmployment.objects.filter(person=primary)
                employment = history.filter(status=PersonEmployment.Status.ACTIVE).filter(
                    models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
                ).filter(
                    models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
                ).order_by("-valid_from", "-pk").first()
                company_id = employment.company_id if employment else (
                    (primary.company_id or person.company_id) if not history.exists() else None
                )
                if not company_id:
                    raise ValueError(f"ردیف {row_number}: شرکت محل اشتغال فعلی مالک شخصی قابل تعیین نیست.")
                if person.company_id and person.company_id != company_id:
                    raise ValueError(
                        f"ردیف {row_number}: شرکت ثبت‌شده در مشخصات مالک با سابقه اشتغال فعلی او مغایرت دارد؛ ابتدا سوابق شرکت اصلاح شود."
                    )
            if not contract.companies.filter(pk=company_id).exists():
                raise ValueError(f"ردیف {row_number}: قرارداد برای شرکت مالک این دارایی تعریف نشده است.")

            insured_value = _parse_amount(raw.get("insured_value"), row_number, "insured_value")
            market_value = _parse_amount(raw.get("market_value"), row_number, "market_value")
            if insured_value <= 0 or market_value <= 0:
                raise ValueError(f"ردیف {row_number}: ارزش بیمه‌شده و ارزش روز باید بزرگ‌تر از صفر باشند.")
            policy_start = _parse_date(raw.get("policy_start"), row_number, "policy_start")
            policy_end = _parse_date(raw.get("policy_end"), row_number, "policy_end")
            valuation_date = _parse_date(raw.get("valuation_date"), row_number, "valuation_date")
            if not policy_start or not policy_end or not valuation_date or policy_end < policy_start:
                raise ValueError(f"ردیف {row_number}: تاریخ شروع/پایان پوشش و تاریخ ارزیابی باید معتبر باشند.")
            if policy_start < contract.start_date or policy_end > contract.end_date:
                raise ValueError(f"ردیف {row_number}: بازه بیمه‌نامه باید داخل بازه قرارداد باشد.")
            if valuation_date > today:
                raise ValueError(f"ردیف {row_number}: تاریخ ارزیابی نمی‌تواند در آینده باشد.")
            valuation_method = _text(raw.get("valuation_method")).lower()
            if valuation_method not in valuation_methods:
                raise ValueError(f"ردیف {row_number}: روش ارزیابی باید formal، expert یا declared باشد.")

            plate_number = _text(raw.get("plate_number"))
            vin = _text(raw.get("vin"))
            engine_number = _text(raw.get("engine_number"))
            make = _text(raw.get("make"))
            model_name = _text(raw.get("model_name"))
            model_year_raw = _text(raw.get("model_year")).translate(PERSIAN_DIGITS)
            model_year = None
            if asset_type == InsuredAsset.Type.VEHICLE:
                if not plate_number:
                    raise ValueError(f"ردیف {row_number}: شماره پلاک برای دارایی خودرو الزامی است.")
                if model_year_raw:
                    try:
                        model_year = int(model_year_raw)
                    except ValueError:
                        raise ValueError(f"ردیف {row_number}: سال ساخت خودرو باید عددی باشد.")
                    if not 1886 <= model_year <= today.year + 1:
                        raise ValueError(f"ردیف {row_number}: سال ساخت خودرو خارج از بازه معتبر است.")
            elif any((plate_number, vin, engine_number, make, model_name, model_year_raw)):
                raise ValueError(f"ردیف {row_number}: مشخصات خودرو فقط برای نوع vehicle مجاز است.")

            valid.append({
                "asset_code": asset_code,
                "name": name,
                "asset_type": asset_type,
                "owner_type": owner_type,
                "company_id": company.pk if company else None,
                "company_code": company.code if company else "",
                "person_id": person.pk if person else None,
                "owner_national_id": person.national_id if person else "",
                "identifier": _text(raw.get("identifier"))[:120],
                "location": _text(raw.get("location"))[:250],
                "insured_value": str(insured_value),
                "contract_id": contract.pk,
                "contract_number": contract.code,
                "insurer_id": contract.insurer_id,
                "policy_number": policy_number,
                "policy_start": policy_start.isoformat(),
                "policy_end": policy_end.isoformat(),
                "valuation_date": valuation_date.isoformat(),
                "market_value": str(market_value),
                "valuation_method": valuation_method,
                "plate_number": plate_number[:40],
                "vin": vin[:80],
                "engine_number": engine_number[:80],
                "make": make[:100],
                "model_name": model_name[:100],
                "model_year": model_year,
                "source_row": row_number,
            })
            seen_assets.add(asset_code)
            seen_policies.add(policy_number)
        except (ValueError, ValidationError, PermissionDenied) as exc:
            errors.append(str(exc))
    return valid, errors


def _preview_contracts(user, mapped_rows):
    valid, errors, seen = [], [], set()
    allowed_lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
    for row_number, raw in mapped_rows:
        try:
            code = _text(raw.get("code"))
            title = _text(raw.get("title"))
            insurer_name = _text(raw.get("insurer_name"))
            line = _text(raw.get("line"))
            if not all((code, title, insurer_name, line)):
                raise ValueError(f"ردیف {row_number}: شماره، عنوان، بیمه‌گر و رشته قرارداد الزامی است.")
            if line not in dict(InsuranceLine.choices):
                raise ValueError(f"ردیف {row_number}: رشته بیمه معتبر نیست.")
            if not has_global_access(user) and "*" not in allowed_lines and line not in allowed_lines:
                raise ValueError(f"ردیف {row_number}: رشته قرارداد خارج از انتصاب شماست.")
            if code in seen or Contract.objects.filter(code=code).exists():
                raise ValueError(f"ردیف {row_number}: شماره قرارداد تکراری است.")
            insurer = Insurer.objects.filter(name=insurer_name, is_active=True).first()
            if not insurer:
                raise ValueError(f"ردیف {row_number}: بیمه‌گر فعال با نام دقیق «{insurer_name}» یافت نشد.")
            company_codes = [part.strip() for part in _text(raw.get("company_codes")).replace(",", ";").split(";") if part.strip()]
            if not company_codes or len(company_codes) != len(set(company_codes)):
                raise ValueError(f"ردیف {row_number}: کد شرکت‌ها خالی یا تکراری است.")
            companies = list(Company.objects.filter(code__in=company_codes, is_active=True))
            if len(companies) != len(company_codes):
                raise ValueError(f"ردیف {row_number}: یک یا چند کد شرکت فعال و معتبر نیست.")
            start_date = _parse_date(raw.get("start_date"), row_number, "start_date")
            end_date = _parse_date(raw.get("end_date"), row_number, "end_date")
            effective_date = _parse_date(raw.get("effective_date"), row_number, "effective_date")
            if not start_date or not end_date or not effective_date or end_date < start_date:
                raise ValueError(f"ردیف {row_number}: بازه قرارداد یا تاریخ اثر معتبر نیست.")
            if not start_date <= effective_date <= end_date:
                raise ValueError(f"ردیف {row_number}: تاریخ اثر باید داخل بازه قرارداد باشد.")
            description = _text(raw.get("revision_description"))
            if len(description) < 5:
                raise ValueError(f"ردیف {row_number}: شرح نسخه باید حداقل ۵ نویسه باشد.")
            valid.append({
                "code": code[:80],
                "title": title[:250],
                "insurer_id": insurer.pk,
                "insurer_name": insurer.name,
                "line": line,
                "company_ids": [company.pk for company in companies],
                "company_codes": company_codes,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "effective_date": effective_date.isoformat(),
                "revision_description": description[:4000],
                "coverage_summary": _text(raw.get("coverage_summary"))[:4000],
                "terms": _text(raw.get("terms"))[:8000],
                "_row": row_number,
            })
            seen.add(code)
        except (ValueError, ValidationError, PermissionDenied) as exc:
            errors.append(str(exc))
    return valid, errors


@login_required
def import_center(request):
    profiles = []
    for code, profile in PROFILES.items():
        if _profile_allowed(request.user, code):
            profiles.append({"code": code, **profile})
    if not profiles:
        raise PermissionDenied
    return render(request, "imports/import_center.html", {"profiles": profiles})


@login_required
def profile_sample(request, profile):
    spec = get_profile(profile)
    if not spec or not _profile_allowed(request.user, profile):
        raise PermissionDenied
    sample_rows = spec["sample"]
    return render(request, "imports/profile_sample.html", {
        "profile_code": profile,
        "profile": spec,
        "sample_rows": sample_rows,
    })


@login_required
def download_profile_template(request, profile):
    spec = get_profile(profile)
    if not spec or not _profile_allowed(request.user, profile):
        raise PermissionDenied
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "نمونه ورود"
    headers = [field[0] for field in spec["fields"]]
    labels = [field[1] for field in spec["fields"]]
    sheet.append(headers)
    for example in spec["sample"]:
        sheet.append(example)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="243B53")
    for column_number, header in enumerate(headers, start=1):
        sheet.column_dimensions[get_column_letter(column_number)].width = min(max(len(header) + 4, 16), 34)
    guide = workbook.create_sheet("راهنما")
    guide.append(["نام فیلد", "شرح و نکته", "ستون پیش‌فرض", "اجباری"])
    for key, label, default, required in spec["fields"]:
        guide.append([key, label, default, "بله" if required else "خیر"])
    guide.freeze_panes = "A2"
    for cell in guide[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="243B53")
    guide.column_dimensions["A"].width = 30
    guide.column_dimensions["B"].width = 70
    guide.column_dimensions["C"].width = 18
    guide.column_dimensions["D"].width = 14
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{spec["template_name"]}"'
    return response


@login_required
def profile_import(request, profile):
    spec = get_profile(profile)
    if not spec or not _profile_allowed(request.user, profile):
        raise PermissionDenied
    if profile == "people_roster":
        representative_ids = company_ids_for(request.user, role=RoleAssignment.Role.SUBSIDIARY_REP)
        is_staff_user = _staff(request.user)
        if not representative_ids and not is_staff_user:
            raise PermissionDenied
    form = FlexibleExcelImportForm(request.POST or None, request.FILES or None, profile=spec)
    batch = None
    errors = []
    preview_rows = []
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        file_error = validate_uploaded_file(
            upload, max_size=25 * 1024 * 1024, allowed_extensions={".xlsx", ".xlsm"}
        )
        if file_error:
            form.add_error("file", file_error)
        else:
            mapping = form.column_mapping
            try:
                mapped_rows = _mapped_rows(upload, mapping, form.cleaned_data["header_row"])
                if profile == "people_roster":
                    valid_rows, errors = _preview_people(request.user, mapped_rows)
                elif profile == "claims":
                    valid_rows, errors = _preview_claims(request.user, mapped_rows)
                elif profile == "assets":
                    valid_rows, errors = _preview_assets(request.user, mapped_rows)
                else:
                    valid_rows, errors = _preview_contracts(request.user, mapped_rows)
                upload.seek(0)
                batch = ImportBatch.objects.create(
                    batch_number="IMP-" + secrets.token_hex(5).upper(),
                    source_type=profile,
                    file=upload,
                    uploaded_by=request.user,
                    status=(
                        ImportBatch.Status.VALIDATED
                        if valid_rows else ImportBatch.Status.FAILED
                    ),
                    total_rows=len(valid_rows) + len(errors),
                    valid_rows=len(valid_rows),
                    invalid_rows=len(errors),
                    result_report="\n".join(errors[:300]),
                    preview_data=valid_rows,
                    column_mapping={**mapping, "_header_row": form.cleaned_data["header_row"]},
                )
                preview_rows = valid_rows[:MAX_PREVIEW_ROWS]
            except (ValueError, ValidationError) as exc:
                form.add_error("file", str(exc))
    candidate_batches = ImportBatch.objects.filter(
        status=ImportBatch.Status.VALIDATED,
        source_type=profile,
    ).select_related("uploaded_by").order_by("-created_at")[:100]
    pending_batches = []
    for item in candidate_batches:
        item.can_confirm = _can_review_batch(request.user, item) and item.uploaded_by_id != request.user.pk
        if item.uploaded_by_id == request.user.pk or item.can_confirm:
            pending_batches.append(item)
        if len(pending_batches) >= 30:
            break
    return render(request, "imports/profile_import.html", {
        "profile_code": profile,
        "profile": spec,
        "form": form,
        "batch": batch,
        "errors": errors[:100],
        "preview_rows": preview_rows,
        "confirm_available": bool(batch and batch.valid_rows and _can_review(request.user, profile) and batch.uploaded_by_id != request.user.pk),
        "pending_batches": pending_batches,
        "can_confirm_batches": _can_review(request.user, profile),
    })


def _process_people_batch(batch, reviewer):
    today = timezone.localdate()
    reviewer_allowed = (
        has_global_access(reviewer)
        or has_role(reviewer, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code="health")
    )
    if not reviewer_allowed:
        raise PermissionDenied("تأییدکننده به فرآیند فهرست بیمه‌شدگان دسترسی معتبر ندارد.")

    for row in batch.preview_data:
        company = Company.objects.filter(pk=row["company_id"], is_active=True).first()
        if not company or company.code != row["company_code"]:
            raise ValidationError("شرکت این ردیف پس از پیش‌نمایش غیرفعال یا تغییر کرده است.")
        uploader = batch.uploaded_by
        uploader_still_authorized = (
            has_global_access(uploader)
            or has_role(uploader, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code="health")
            or has_role(uploader, RoleAssignment.Role.SUBSIDIARY_REP, company_id=company.pk)
        )
        if not uploader_still_authorized:
            raise PermissionDenied("انتصاب بارگذار برای شرکت این ردیف معتبر نیست یا لغو شده است.")

        action = row["action"]
        person = Person.objects.filter(national_id=row["national_id"]).first()
        if action == "add_employee":
            if person:
                if person.relationship != Person.Relationship.EMPLOYEE or person.employee_id:
                    raise ValidationError("کد ملی کارمند اکنون به فرد تحت تکفل یا شخصی با هویت ناسازگار تعلق دارد.")
                history = PersonEmployment.objects.filter(person=person)
                if history.filter(status=PersonEmployment.Status.ACTIVE).exists():
                    raise ValidationError("برای این کد ملی اشتغال فعال ثبت شده است؛ ورود مجدد مجاز نیست.")
                if not history.filter(company=company).exists():
                    raise ValidationError("تغییر شرکت یا انتقال استخدامی باید از مسیر رسمی انجام شود.")
            else:
                person = Person.objects.create(
                    company=company,
                    national_id=row["national_id"],
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    birth_date=date.fromisoformat(row["birth_date"]),
                    relationship=Person.Relationship.EMPLOYEE,
                    personnel_code=row["personnel_code"],
                    mobile=row["mobile"],
                    iban=row["iban"],
                    is_insured=True,
                    is_active=True,
                )
            if not person.is_active or not person.is_insured:
                person.is_active = True
                person.is_insured = True
                person.save(update_fields=["is_active", "is_insured", "updated_at"])
            PersonEmployment.objects.create(
                person=person, company=company, personnel_code=row["personnel_code"],
                job_title="ثبت گروهی فهرست بیمه‌شدگان", valid_from=today,
                status=PersonEmployment.Status.ACTIVE, source_reference=batch.batch_number,
                created_by=batch.uploaded_by, approved_by=reviewer,
            )

        elif action == "add_dependent":
            if person:
                raise ValidationError("کد ملی فرد تحت تکفل پس از پیش‌نمایش ثبت شده است؛ هیچ رکوردی بازنویسی نمی‌شود.")
            employee = Person.objects.filter(
                national_id=row["employee_national_id"],
                is_active=True,
                relationship=Person.Relationship.EMPLOYEE,
                employee__isnull=True,
            ).first()
            if not employee:
                raise ValidationError("بیمه‌شده اصلی این ردیف دیگر فعال یا معتبر نیست.")
            employee_active = PersonEmployment.objects.filter(
                person=employee, company=company, status=PersonEmployment.Status.ACTIVE
            ).exists()
            if not employee_active and not (
                employee.company_id == company.pk
                and not PersonEmployment.objects.filter(person=employee).exists()
            ):
                raise ValidationError("بیمه‌شده اصلی دیگر در این شرکت اشتغال معتبر ندارد.")
            Person.objects.create(
                company=company, national_id=row["national_id"],
                first_name=row["first_name"], last_name=row["last_name"],
                birth_date=date.fromisoformat(row["birth_date"]),
                relationship=row["relationship"], employee=employee,
                personnel_code=row["personnel_code"], mobile=row["mobile"], iban=row["iban"],
                is_insured=True, is_active=True,
            )

        elif action == "end_employment":
            if not person or not person.is_active:
                raise ValidationError("شخص برای خاتمه همکاری دیگر فعال یا موجود نیست.")
            employments = PersonEmployment.objects.select_for_update().filter(
                person=person, company=company, status=PersonEmployment.Status.ACTIVE
            )
            if employments.count() != 1:
                raise ValidationError("در زمان تأیید باید دقیقاً یک سابقه اشتغال فعال در این شرکت وجود داشته باشد.")
            employment = employments.get()
            employment.status = PersonEmployment.Status.TERMINATED
            employment.valid_until = today
            employment.approved_by = reviewer
            employment.save(update_fields=["status", "valid_until", "approved_by", "updated_at"])
            if not PersonEmployment.objects.filter(
                person=person, status=PersonEmployment.Status.ACTIVE
            ).exists():
                person.is_insured = False
                person.save(update_fields=["is_insured", "updated_at"])


def _process_claims_batch(batch, reviewer, request):
    for row in batch.preview_data:
        contract = Contract.objects.select_related("insurer").filter(
            pk=row["contract_id"],
            is_active=True,
            status=Contract.Status.ACTIVE,
        ).first()
        if not contract:
            raise ValidationError("قرارداد پس از پیش‌نمایش غیرفعال یا از چرخه فعال خارج شده است.")
        service_date = date.fromisoformat(row["service_date"])
        if not (contract.start_date <= service_date <= contract.end_date):
            raise ValidationError("تاریخ خدمت دیگر در بازه اعتبار قرارداد قرار ندارد.")
        company_id = row["company_snapshot_id"]
        if not contract.companies.filter(pk=company_id).exists():
            raise ValidationError("شرکت این خسارت دیگر در محدوده قرارداد قرار ندارد.")
        person = Person.objects.filter(pk=row["person_id"], is_active=True).first()
        if not person:
            raise ValidationError("شخص این خسارت پس از پیش‌نمایش غیرفعال یا حذف‌پذیر نیست.")
        primary = person.employee if person.employee_id else person
        history = PersonEmployment.objects.filter(person=primary)
        matching = history.filter(
            models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=service_date)
        ).filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=service_date)
        ).order_by("-valid_from", "-pk")
        if matching.count() > 1:
            raise ValidationError("سوابق اشتغال در تاریخ خدمت اکنون با هم هم‌پوشانی دارند.")
        employment = matching.first()
        current_company_id = employment.company_id if employment else (
            (primary.company_id or person.company_id) if not history.exists() else None
        )
        if current_company_id != company_id:
            raise ValidationError("شرکت شخص در تاریخ خدمت نسبت به زمان پیش‌نمایش تغییر کرده است.")

        insurer_submitter = has_role(
            batch.uploaded_by, RoleAssignment.Role.INSURER_REP, insurer_id=contract.insurer_id
        )
        specialist_submitter = has_role(
            batch.uploaded_by, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=contract.line
        )
        if not (has_global_access(batch.uploaded_by) or insurer_submitter or specialist_submitter):
            raise PermissionDenied("انتصاب بارگذار برای بیمه‌گر یا رشته این پرونده دیگر معتبر نیست.")
        reviewer_allowed = has_global_access(reviewer) or has_role(
            reviewer, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=contract.line
        )
        if not reviewer_allowed:
            raise PermissionDenied("تأییدکننده به رشته بیمه‌ای این پرونده دسترسی ندارد.")

        source_number = row["source_claim_number"]
        if Claim.objects.filter(insurer_id=contract.insurer_id, source_claim_number=source_number).exists():
            raise ValidationError(f"شماره پرونده منبع {source_number} پس از پیش‌نمایش تکراری شده است.")

        item = dict(row)
        item.pop("_row", None)
        item.pop("national_id", None)
        for field in ("service_date", "registered_date", "source_registered_date", "payment_date"):
            if item.get(field):
                item[field] = date.fromisoformat(item[field])
        if item.get("source_duplicate_reported_at"):
            item["source_duplicate_reported_at"] = datetime.fromisoformat(item["source_duplicate_reported_at"])
        imported_paid_amount = Decimal(str(item.pop("paid_amount", "0") or "0"))
        imported_payment_date = item.pop("payment_date", None)
        claim = Claim.objects.create(**item)
        if imported_paid_amount > 0:
            if not claim.insurer_id:
                raise ValidationError("برای تأیید پرداخت، بیمه‌گر پرونده باید مشخص باشد.")
            record_imported_payment(
                claim_id=claim.pk,
                amount=imported_paid_amount,
                paid_at=imported_payment_date,
                source_reference=claim.source_reference[:160],
                source_insurer=claim.insurer,
                submitted_by=batch.uploaded_by,
                reviewed_by=reviewer,
                note="پرداخت اعلام‌شده در فایل Excel؛ صرفاً ثبت سابقه و بدون انتقال وجه.",
                request=request,
            )


def _process_assets_batch(batch, reviewer, request):
    if not has_global_access(reviewer):
        raise PermissionDenied("تأیید نهایی ورود دارایی‌ها فقط در اختیار رئیس اداره یا مدیر سامانه است.")
    valuation_definition = WorkflowDefinition.objects.filter(
        code="asset_valuation_approval", is_active=True
    ).order_by("-version").first()
    policy_definition = WorkflowDefinition.objects.filter(
        code="asset_policy_approval", is_active=True
    ).order_by("-version").first()
    if not valuation_definition or not policy_definition:
        raise ValidationError("گردش‌کار تصویب ارزیابی یا بیمه‌نامه دارایی فعال نیست؛ seed_operational_workflows را اجرا کنید.")

    today = timezone.localdate()
    for row in batch.preview_data:
        contract = Contract.objects.select_related("insurer").filter(
            pk=row["contract_id"], is_active=True, status=Contract.Status.ACTIVE
        ).first()
        if not contract or contract.code != row["contract_number"]:
            raise ValidationError("قرارداد پس از پیش‌نمایش غیرفعال شده یا تغییر کرده است.")
        if not has_global_access(batch.uploaded_by) and not has_role(
            batch.uploaded_by, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=contract.line
        ):
            raise PermissionDenied("انتصاب بارگذار برای رشته بیمه‌ای این دارایی دیگر معتبر نیست.")
        policy_start = date.fromisoformat(row["policy_start"])
        policy_end = date.fromisoformat(row["policy_end"])
        valuation_date = date.fromisoformat(row["valuation_date"])
        if (
            policy_start < contract.start_date
            or policy_end > contract.end_date
            or policy_end < policy_start
            or valuation_date > today
        ):
            raise ValidationError("تاریخ‌های بیمه‌نامه یا ارزیابی پس از پیش‌نمایش نامعتبر شده‌اند.")
        if InsuredAsset.objects.filter(asset_code=row["asset_code"]).exists():
            raise ValidationError(f"کد دارایی {row['asset_code']} پس از پیش‌نمایش ثبت شده است.")
        if AssetPolicyPeriod.objects.filter(policy_number=row["policy_number"]).exists():
            raise ValidationError(f"شماره بیمه‌نامه {row['policy_number']} پس از پیش‌نمایش ثبت شده است.")

        company = None
        person = None
        if row["owner_type"] == "company":
            company = Company.objects.filter(
                pk=row["company_id"], code=row["company_code"], is_active=True
            ).first()
            if not company:
                raise ValidationError("شرکت مالک این دارایی پس از پیش‌نمایش غیرفعال شده یا تغییر کرده است.")
            company_id = company.pk
        else:
            person = Person.objects.filter(
                pk=row["person_id"],
                national_id=row["owner_national_id"],
                is_active=True,
            ).first()
            if not person:
                raise ValidationError("مالک شخصی این دارایی پس از پیش‌نمایش غیرفعال شده یا تغییر کرده است.")
            primary = person.employee if person.employee_id else person
            history = PersonEmployment.objects.filter(person=primary)
            employment = history.filter(status=PersonEmployment.Status.ACTIVE).filter(
                models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
            ).filter(
                models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
            ).order_by("-valid_from", "-pk").first()
            company_id = employment.company_id if employment else (
                (primary.company_id or person.company_id) if not history.exists() else None
            )
            if not company_id:
                raise ValidationError("شرکت محل اشتغال فعلی مالک شخصی دیگر قابل تعیین نیست.")
            if person.company_id and person.company_id != company_id:
                raise ValidationError("شرکت ثبت‌شده در مشخصات مالک با سابقه اشتغال فعلی او مغایرت دارد.")
        if not contract.companies.filter(pk=company_id).exists():
            raise ValidationError("شرکت مالک این دارایی دیگر در محدوده قرارداد قرار ندارد.")

        asset = InsuredAsset.objects.create(
            asset_code=row["asset_code"],
            name=row["name"],
            asset_type=row["asset_type"],
            company=company,
            person=person,
            identifier=row["identifier"],
            location=row["location"],
            insured_value=Decimal(row["insured_value"]),
            insurer=contract.insurer,
            contract=contract,
            policy_number=row["policy_number"],
            policy_start=policy_start,
            policy_end=policy_end,
            is_active=True,
            notes=f"ثبت گروهی از فایل Excel؛ شماره عملیات {batch.batch_number}.",
            created_by=batch.uploaded_by,
        )
        if asset.asset_type == InsuredAsset.Type.VEHICLE:
            Vehicle.objects.create(
                asset=asset,
                plate_number=row["plate_number"],
                vin=row["vin"],
                engine_number=row["engine_number"],
                make=row["make"],
                model_name=row["model_name"],
                model_year=row["model_year"],
            )

        valuation = AssetValuation.objects.create(
            asset=asset,
            valuation_date=valuation_date,
            market_value=Decimal(row["market_value"]),
            insured_value=Decimal(row["insured_value"]),
            method=row["valuation_method"],
            status=AssetValuation.Status.PENDING_APPROVAL,
            source_reference=batch.batch_number,
            note="ارزیابی پیشنهادی واردشده از Excel؛ در انتظار تصویب مستقل.",
            created_by=batch.uploaded_by,
        )
        policy_period = AssetPolicyPeriod.objects.create(
            asset=asset,
            insurer=contract.insurer,
            contract=contract,
            policy_number=row["policy_number"],
            policy_start=policy_start,
            policy_end=policy_end,
            status=AssetPolicyPeriod.Status.PENDING_APPROVAL,
            source_reference=batch.batch_number,
            note="دوره بیمه‌نامه واردشده از Excel؛ تا تصویب نهایی فعال نمی‌شود.",
            created_by=batch.uploaded_by,
        )

        valuation_assignee, valuation_delegation = resolve_initial_assignee(
            definition=valuation_definition,
            obj=valuation,
            return_delegation=True,
        )
        start_workflow(
            obj=valuation,
            code="asset_valuation_approval",
            actor=reviewer,
            assignee=valuation_delegation.delegate_to if valuation_delegation else valuation_assignee,
            delegation=valuation_delegation,
            note=f"ثبت ارزیابی از عملیات {batch.batch_number}",
        )
        policy_assignee, policy_delegation = resolve_initial_assignee(
            definition=policy_definition,
            obj=policy_period,
            return_delegation=True,
        )
        start_workflow(
            obj=policy_period,
            code="asset_policy_approval",
            actor=reviewer,
            assignee=policy_delegation.delegate_to if policy_delegation else policy_assignee,
            delegation=policy_delegation,
            note=f"ثبت دوره بیمه‌نامه از عملیات {batch.batch_number}",
        )
        record_event(
            actor=reviewer,
            action="asset_excel_import_registered",
            obj=asset,
            summary="دارایی و دو پرونده تصویب ارزیابی/بیمه‌نامه از فایل Excel ثبت شدند.",
            after_data={
                "batch_id": batch.pk,
                "valuation_id": valuation.pk,
                "policy_period_id": policy_period.pk,
                "asset_code": asset.asset_code,
            },
            request=request,
        )


def _process_contracts_batch(batch, reviewer):
    from workflow.models import WorkflowDefinition

    if not has_global_access(reviewer):
        raise PermissionDenied("تصویب دسته قراردادهای جدید فقط در اختیار رئیس اداره یا مدیر سامانه است.")
    definition = WorkflowDefinition.objects.filter(code="contract_approval", is_active=True).order_by("-version").first()
    if not definition:
        raise ValidationError("گردش‌کار فعال contract_approval موجود نیست؛ ابتدا seed_operational_workflows را اجرا کنید.")
    for row in batch.preview_data:
        if not has_global_access(batch.uploaded_by) and not has_role(
            batch.uploaded_by, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=row["line"]
        ):
            raise PermissionDenied("انتصاب بارگذار برای رشته این قرارداد دیگر معتبر نیست.")
        if Contract.objects.filter(code=row["code"]).exists():
            raise ValidationError(f"شماره قرارداد {row['code']} پس از پیش‌نمایش ثبت شده است.")
        insurer = Insurer.objects.filter(pk=row["insurer_id"], is_active=True).first()
        if not insurer:
            raise ValidationError("بیمه‌گر انتخاب‌شده پس از پیش‌نمایش غیرفعال شده است.")
        companies = list(Company.objects.filter(pk__in=row["company_ids"], is_active=True))
        if len(companies) != len(set(row["company_ids"])):
            raise ValidationError("یک یا چند شرکت انتخاب‌شده پس از پیش‌نمایش غیرفعال شده‌اند.")
        start_date = date.fromisoformat(row["start_date"])
        end_date = date.fromisoformat(row["end_date"])
        effective_date = date.fromisoformat(row["effective_date"])
        if end_date < start_date or not start_date <= effective_date <= end_date:
            raise ValidationError("بازه قرارداد یا تاریخ اثر هنگام تأیید معتبر نیست.")

        contract = Contract.objects.create(
            code=row["code"],
            title=row["title"],
            insurer=insurer,
            line=row["line"],
            start_date=start_date,
            end_date=end_date,
            coverage_summary=row["coverage_summary"],
            terms=row["terms"],
            status=Contract.Status.DRAFT,
            is_active=False,
        )
        contract.companies.set(companies)
        snapshot = {
            "code": contract.code,
            "title": contract.title,
            "insurer_id": insurer.pk,
            "line": contract.line,
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "coverage_summary": contract.coverage_summary,
            "terms": contract.terms,
            "company_ids": sorted(row["company_ids"]),
        }
        revision = ContractRevision.objects.create(
            contract=contract,
            revision_number=1,
            description=row["revision_description"],
            created_by=batch.uploaded_by,
            status=ContractRevision.Status.PENDING_APPROVAL,
            snapshot=snapshot,
            effective_date=effective_date,
        )
        assignee, delegation = resolve_initial_assignee(
            definition=definition,
            obj=revision,
            return_delegation=True,
            insurer_id=insurer.pk,
            line_code=contract.line,
        )
        case = start_workflow(
            obj=revision,
            code="contract_approval",
            actor=reviewer,
            assignee=assignee,
            delegation=delegation,
            note=row["revision_description"],
        )
        record_event(
            actor=reviewer,
            action="contract_excel_import_submitted",
            obj=contract,
            summary="قرارداد واردشده از Excel به‌صورت پیش‌نویس ثبت و برای تأیید ارسال شد.",
            after_data={"revision_id": revision.pk, "workflow_case_id": case.pk, "batch_id": batch.pk},
            request=None,
        )



@login_required
def profile_import_confirm(request, batch_id):
    if request.method != "POST":
        raise PermissionDenied
    batch = get_object_or_404(ImportBatch.objects.select_related("uploaded_by"), pk=batch_id)
    profile = batch.source_type
    if profile not in PROFILES or not _can_review_batch(request.user, batch):
        raise PermissionDenied
    if batch.uploaded_by_id == request.user.pk:
        raise PermissionDenied("بارگذار فایل اجازه تأیید نهایی همان فایل را ندارد.")
    try:
        with transaction.atomic():
            batch = get_object_or_404(
                ImportBatch.objects.select_for_update(),
                pk=batch_id,
                status=ImportBatch.Status.VALIDATED,
            )
            if not isinstance(batch.preview_data, list) or len(batch.preview_data) != batch.valid_rows or not batch.preview_data:
                raise PermissionDenied("پیش‌نمایش این فایل معتبر یا قابل ثبت نیست.")
            if profile == "people_roster":
                _process_people_batch(batch, request.user)
            elif profile == "claims":
                _process_claims_batch(batch, request.user, request)
            elif profile == "assets":
                _process_assets_batch(batch, request.user, request)
            else:
                _process_contracts_batch(batch, request.user)
            batch.status = ImportBatch.Status.PROCESSED
            batch.reviewed_by = request.user
            batch.reviewed_at = timezone.now()
            batch.review_note = request.POST.get("review_note", "").strip()[:4000]
            batch.preview_data = []
            batch.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "preview_data"])
            record_event(
                actor=request.user,
                action="excel_import_batch_confirmed",
                obj=batch,
                summary=f"ورود گروهی {profile} با {batch.valid_rows} ردیف معتبر تأیید شد.",
                after_data={
                    "source_type": profile,
                    "valid_rows": batch.valid_rows,
                    "invalid_rows": batch.invalid_rows,
                    "uploaded_by_id": batch.uploaded_by_id,
                },
                request=request,
            )
    except (IntegrityError, ValidationError, ValueError, PermissionDenied) as exc:
        messages.error(request, f"ثبت نهایی انجام نشد؛ هیچ ردیفی ثبت نشد: {exc}")
        return redirect("profile_import", profile=profile)
    messages.success(request, f"ثبت نهایی انجام شد: {batch.valid_rows} ردیف؛ {batch.invalid_rows} ردیف دارای خطا وارد نشد.")
    return redirect("profile_import", profile=profile)
