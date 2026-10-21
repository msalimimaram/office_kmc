import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from openpyxl import load_workbook

from claims.models import Claim
from organizations.models import Person
from .forms import ClaimImportForm
from .models import ImportBatch
from auditlog.models import AuditEvent

IMPORT_ROLES = {"system_admin", "department_head", "insurance_specialist", "insurer"}

def _can_import(user):
    return user.is_superuser or user.role in IMPORT_ROLES

@login_required
def claim_import(request):
    if not _can_import(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = ClaimImportForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                wb = load_workbook(upload, read_only=True, data_only=True)
                ws = wb.active
                rows = ws.iter_rows(values_only=True)
                headers = [str(v).strip().lower() if v is not None else "" for v in next(rows)]
                required = {"claim_number", "national_id", "service_type"}
                if not required.issubset(set(headers)):
                    form.add_error("file", "ستون‌های اجباری: claim_number، national_id و service_type هستند.")
                    return render(request, "imports/claim_import.html", {"form": form})
                idx = {name: headers.index(name) for name in headers if name}
                data, errors, seen = [], [], set()
                for line, row in enumerate(rows, start=2):
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
                    if claim_no in seen or Claim.objects.filter(claim_number=claim_no).exists():
                        errors.append(f"ردیف {line}: شناسه خسارت {claim_no} تکراری است.")
                        continue
                    seen.add(claim_no)
                    person = Person.objects.filter(national_id=nid, is_active=True).first()
                    if not person:
                        errors.append(f"ردیف {line}: شخصی با کد ملی واردشده یافت نشد.")
                        continue
                    def amount(key):
                        value = val(key)
                        if value in (None, ""):
                            return Decimal("0")
                        try:
                            return Decimal(str(value).replace(",", ""))
                        except InvalidOperation:
                            raise ValueError(f"ردیف {line}: ستون {key} باید عددی باشد.")
                    try:
                        requested, assessed, payable, paid = [
                            amount(k) for k in ("requested_amount", "assessed_amount", "payable_amount", "paid_amount")
                        ]
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    def date_value(key):
                        value = val(key)
                        if not value:
                            return None
                        if isinstance(value, datetime):
                            return value.date()
                        try:
                            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
                        except ValueError:
                            return None
                    data.append({
                        "claim_number": claim_no, "person_id": person.pk, "service_type": service[:120],
                        "requested_amount": str(requested), "assessed_amount": str(assessed),
                        "payable_amount": str(payable), "paid_amount": str(paid),
                        "service_date": date_value("service_date").isoformat() if date_value("service_date") else None,
                        "registered_date": date_value("registered_date").isoformat() if date_value("registered_date") else None,
                        "payment_date": date_value("payment_date").isoformat() if date_value("payment_date") else None,
                        "source_reference": upload.name[:200],
                    })
                wb.close()
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
                    "errors": errors[:100], "confirm_available": bool(data),
                })
            except Exception as exc:
                form.add_error("file", f"فایل قابل پردازش نیست یا ساختار آن معتبر نیست: {exc}")
    else:
        form = ClaimImportForm()
    return render(request, "imports/claim_import.html", {"form": form})

@login_required
def claim_import_confirm(request, batch_id):
    if request.method != "POST" or not _can_import(request.user):
        raise PermissionDenied
    batch = get_object_or_404(
        ImportBatch, pk=batch_id, uploaded_by=request.user, status=ImportBatch.Status.VALIDATED
    )
    with transaction.atomic():
        for row in batch.preview_data:
            item = dict(row)
            item["person_id"] = item.pop("person_id")
            for field in ("service_date", "registered_date", "payment_date"):
                if item.get(field):
                    item[field] = datetime.fromisoformat(item[field]).date()
            Claim.objects.create(**item)
        batch.status = ImportBatch.Status.PROCESSED
        batch.preview_data = []
        batch.save(update_fields=["status", "preview_data"])
    AuditEvent.objects.create(
        actor=request.user, action="claim_excel_import", object_type="ImportBatch",
        object_id=str(batch.pk), summary=f"{batch.valid_rows} ردیف ثبت شد؛ {batch.invalid_rows} خطا"
    )
    messages.success(request, f"ثبت نهایی انجام شد: {batch.valid_rows} خسارت؛ {batch.invalid_rows} ردیف خطا.")
    return redirect("claim_import")
