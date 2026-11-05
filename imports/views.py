import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from openpyxl import load_workbook

from claims.models import Claim, ClaimPayment
from insurance.models import Contract
from organizations.models import Person
from .forms import ClaimImportForm
from .models import ImportBatch
from auditlog.models import AuditEvent
from accounts.access import has_global_access, has_role, insurer_ids_for, line_codes_for
from accounts.models import RoleAssignment
import jdatetime

MAX_IMPORT_ROWS = 10000


def _can_import(user):
    if has_global_access(user) or has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        return True
    return has_role(user, RoleAssignment.Role.INSURER_REP) and len(insurer_ids_for(user)) == 1


def _can_confirm_import(user):
    if has_global_access(user):
        return True
    if has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST):
        lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        return "*" in lines or "health" in lines
    return False


def _parse_amount(value, line, key):
    if value in (None, ""):
        return Decimal("0")
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"ردیف {line}: ستون {key} باید عددی باشد.")
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"ردیف {line}: ستون {key} باید عددی معتبر و نامنفی باشد.")
    exponent = amount.as_tuple().exponent
    integer_digits = max(0, len(amount.as_tuple().digits) + exponent)
    decimal_places = max(0, -exponent)
    if integer_digits > 14 or decimal_places > 2:
        raise ValueError(f"ردیف {line}: ستون {key} حداکثر ۱۴ رقم صحیح و ۲ رقم اعشار می‌پذیرد.")
    return amount


def _parse_date(value, line, key):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            parsed = datetime.strptime(raw[:10], pattern).date()
            if 1300 <= parsed.year <= 1499:
                return jdatetime.date(parsed.year, parsed.month, parsed.day).togregorian()
            return parsed
        except (TypeError, ValueError):
            continue
    raise ValueError(f"ردیف {line}: تاریخ ستون {key} معتبر نیست؛ تاریخ میلادی یا شمسی قابل تبدیل وارد کنید.")


@login_required
def claim_import(request):
    if not _can_import(request.user):
        raise PermissionDenied
    insurer_ids = insurer_ids_for(request.user)
    is_insurer = has_role(request.user, RoleAssignment.Role.INSURER_REP)
    insurer_id = next(iter(insurer_ids)) if is_insurer and len(insurer_ids) == 1 else None
    if has_role(request.user, RoleAssignment.Role.INSURANCE_SPECIALIST) and not has_global_access(request.user):
        specialist_lines = line_codes_for(request.user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if "*" not in specialist_lines and "health" not in specialist_lines:
            raise PermissionDenied("ورود خسارت درمان فقط برای کارشناس درمان مجاز است.")
    if request.method == "POST":
        form = ClaimImportForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            wb = None
            try:
                wb = load_workbook(upload, read_only=True, data_only=True)
                ws = wb.active
                rows = ws.iter_rows(values_only=True)
                headers = next(rows, None)
                if not headers:
                    form.add_error("file", "فایل اکسل خالی است.")
                    return render(request, "imports/claim_import.html", {"form": form})
                headers = [str(v).strip().lower() if v is not None else "" for v in headers]
                required = {"claim_number", "national_id", "service_type"}
                if not required.issubset(set(headers)):
                    form.add_error("file", "ستون‌های اجباری: claim_number، national_id و service_type هستند.")
                    return render(request, "imports/claim_import.html", {"form": form})
                idx = {name: headers.index(name) for name in headers if name}
                data, errors, seen = [], [], set()
                for line, row in enumerate(rows, start=2):
                    if line > MAX_IMPORT_ROWS + 1:
                        errors.append(f"حداکثر تعداد ردیف داده در هر فایل {MAX_IMPORT_ROWS} است؛ فایل به این حد رسید.")
                        break
                    if not any(v is not None for v in row):
                        continue

                    def val(key):
                        i = idx.get(key)
                        return row[i] if i is not None and i < len(row) else None

                    claim_no = str(val("claim_number") or "").strip()
                    nid = str(val("national_id") or "").strip()
                    if nid.endswith(".0"):
                        nid = nid[:-2]
                    service = str(val("service_type") or "").strip()
                    if not claim_no or not nid or not service:
                        errors.append(f"ردیف {line}: شناسه خسارت، کد ملی و نوع خدمت الزامی است.")
                        continue
                    if len(claim_no) > 100:
                        errors.append(f"ردیف {line}: شناسه خسارت بیش از حد مجاز طولانی است.")
                        continue
                    if claim_no in seen or Claim.objects.filter(claim_number=claim_no).exists():
                        errors.append(f"ردیف {line}: شناسه خسارت {claim_no} تکراری است.")
                        continue
                    people = Person.objects.filter(national_id=nid, is_active=True)
                    if is_insurer:
                        allowed_company_ids = Contract.objects.filter(
                            insurer_id=insurer_id, is_active=True
                        ).values_list("companies__id", flat=True)
                        people = people.filter(company_id__in=allowed_company_ids, is_insured=True)
                    count = people.count()
                    if count == 0:
                        errors.append(f"ردیف {line}: شخصی با کد ملی واردشده یافت نشد.")
                        continue
                    if count > 1:
                        errors.append(f"ردیف {line}: کد ملی در چند شرکت یافت شد؛ داده‌ها باید رفع ابهام شوند.")
                        continue
                    person = people.get()
                    try:
                        amounts = {
                            key: _parse_amount(val(key), line, key)
                            for key in ("requested_amount", "assessed_amount", "payable_amount", "paid_amount")
                        }
                        dates = {
                            key: _parse_date(val(key), line, key)
                            for key in ("service_date", "registered_date", "payment_date")
                        }
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    if amounts["paid_amount"] > amounts["payable_amount"]:
                        errors.append(f"ردیف {line}: مبلغ پرداختی نمی‌تواند از مبلغ قابل پرداخت بیشتر باشد.")
                        continue
                    if dates["payment_date"] and not amounts["paid_amount"]:
                        errors.append(f"ردیف {line}: تاریخ پرداخت بدون مبلغ پرداختی ثبت شده است.")
                        continue
                    seen.add(claim_no)
                    data.append({
                        "claim_number": claim_no, "person_id": person.pk, "national_id": nid,
                        "service_type": service[:120],
                        **{key: str(value) for key, value in amounts.items()},
                        **{key: value.isoformat() if value else None for key, value in dates.items()},
                        "source_reference": upload.name[:200],
                        "insurer_id": insurer_id if is_insurer else None,
                    })
                batch = ImportBatch.objects.create(
                    batch_number="IMP-" + secrets.token_hex(5).upper(),
                    file=upload, uploaded_by=request.user, total_rows=len(data) + len(errors),
                    valid_rows=len(data), invalid_rows=len(errors),
                    status=ImportBatch.Status.VALIDATED,
                    result_report="\n".join(errors[:300]),
                    preview_data=data,
                )
                return render(request, "imports/claim_import.html", {
                    "form": ClaimImportForm(), "batch": batch, "preview_count": len(data),
                    "errors": errors[:100], "confirm_available": bool(data) and _can_confirm_import(request.user), "preview_rows": data[:20],
                })
            except Exception:
                form.add_error("file", "فایل قابل پردازش نیست یا ساختار آن معتبر نیست. قالب فایل و ستون‌ها را بررسی کنید.")
            finally:
                if wb is not None:
                    wb.close()
    else:
        form = ClaimImportForm()
    pending_batches = ImportBatch.objects.filter(status=ImportBatch.Status.VALIDATED).select_related("uploaded_by").order_by("created_at") if _can_confirm_import(request.user) else ImportBatch.objects.filter(uploaded_by=request.user, status=ImportBatch.Status.VALIDATED).order_by("-created_at")
    return render(request, "imports/claim_import.html", {"form": form, "pending_batches": pending_batches, "can_confirm_batches": _can_confirm_import(request.user)})


@login_required
def claim_import_confirm(request, batch_id):
    if request.method != "POST" or not _can_confirm_import(request.user):
        raise PermissionDenied
    with transaction.atomic():
        batch = get_object_or_404(
            ImportBatch.objects.select_for_update(),
            pk=batch_id, status=ImportBatch.Status.VALIDATED
        )
        # A concurrent confirmation cannot process the same batch twice.
        for row in batch.preview_data:
            item = dict(row)
            item.pop("national_id", None)
            for field in ("service_date", "registered_date", "payment_date"):
                if item.get(field):
                    item[field] = datetime.fromisoformat(item[field]).date()
            claim = Claim.objects.create(**item)
            if claim.paid_amount and claim.paid_amount > 0:
                ClaimPayment.objects.create(
                    claim=claim,
                    amount=claim.paid_amount,
                    paid_at=claim.payment_date,
                    source_reference=claim.source_reference,
                    source_insurer=claim.insurer,
                    recorded_by=batch.uploaded_by,
                    confirmed_by=request.user,
                    is_legacy_import=True,
                    note="Imported aggregate payment; this records source data and does not transfer money.",
                )
        batch.status = ImportBatch.Status.PROCESSED
        batch.reviewed_by = request.user
        batch.reviewed_at = timezone.now()
        batch.review_note = request.POST.get("review_note", "").strip()[:4000]
        batch.preview_data = []
        batch.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "preview_data"])
        AuditEvent.objects.create(
            actor=request.user, action="claim_excel_import", object_type="ImportBatch",
            object_id=str(batch.pk), summary=f"{batch.valid_rows} ردیف ثبت شد؛ {batch.invalid_rows} خطا"
        )
    messages.success(request, f"ثبت نهایی انجام شد: {batch.valid_rows} خسارت؛ {batch.invalid_rows} ردیف خطا.")
    return redirect("claim_import")
