"""Safe, domain-aware summaries for workflow inbox and case-detail screens.

This module deliberately exposes presentation fields, not arbitrary model
serialization. Sensitive records get reduced summaries.
"""

from accounts.access import has_global_access, is_insurance_staff, is_unit_manager


def _text(value):
    if value is None:
        return ""
    return str(value)


def _add(fields, label, value):
    value = _text(value)
    if value:
        fields.append({"label": label, "value": value})


def _display(obj, field):
    method = getattr(obj, f"get_{field}_display", None)
    if callable(method):
        return method()
    return getattr(obj, field, None)


def build_workflow_presentation(case, *, user=None):
    """Return a stable, privacy-aware summary for the workflow's domain record."""
    obj = case.content_object
    if obj is None:
        return {
            "type_label": "رکورد مرتبط",
            "reference": case.object_id,
            "title": case.definition.title,
            "fields": [],
            "description": "",
            "is_confidential": False,
        }

    label = obj._meta.label_lower
    fields = []
    title = case.definition.title
    reference = _text(obj.pk)
    description = ""
    company_name = ""
    person_name = ""
    confidential = bool(getattr(obj, "is_confidential", False))
    is_current_owner = bool(user and case.current_assignee_id == user.pk)
    can_view_internal_notes = bool(
        user and (
            has_global_access(user)
            or is_insurance_staff(user)
            or is_unit_manager(user)
        )
    )
    can_view_confidential_content = bool(
        user and (
            has_global_access(user)
            or (label == "requests_portal.servicerequest" and obj.is_owned_by(user))
        )
    )

    if label == "reports.report":
        latest = obj.latest_version
        return {
            "title": obj.title,
            "subtitle": f"گزارش {obj.get_report_type_display()} — رشته {obj.line_code}",
            "summary": latest.summary if latest else "نسخه محتوایی گزارش ثبت نشده است.",
            "sensitive": False,
        }
    if label == "requests_portal.servicerequest":
        reference = obj.reference
        request_kind = obj.get_kind_display()
        title = (
            obj.title if not confidential or can_view_confidential_content
            else request_kind
        )
        _add(fields, "نوع درخواست", request_kind)
        company_name = _text(getattr(obj, "company", None))
        _add(fields, "شرکت", company_name)
        if not confidential or can_view_confidential_content:
            person_name = _text(getattr(obj, "person", None))
            _add(fields, "بیمه‌شده / متقاضی", person_name)
            _add(fields, "ثبت‌کننده", getattr(obj, "submitted_by", None))
            description = obj.description or ""
        _add(fields, "وضعیت درخواست", obj.get_status_display())

    elif label == "claims.claim":
        reference = obj.claim_number
        title = f"خسارت {obj.claim_number}"
        person_name = _text(getattr(obj, "person", None))
        company_name = _text(getattr(obj, "company_snapshot", None))
        _add(fields, "بیمه‌شده", person_name)
        _add(fields, "شرکت در زمان خسارت", company_name)
        _add(fields, "رشته بیمه", getattr(getattr(obj, "contract", None), "get_line_display", lambda: "")())
        _add(fields, "قرارداد", getattr(obj, "contract", None))
        _add(fields, "بیمه‌گر", getattr(obj, "insurer", None))
        _add(fields, "نوع خدمت", obj.service_type)
        _add(fields, "تاریخ خدمت", obj.service_date)
        _add(fields, "وضعیت خسارت", obj.get_status_display())
        # Assessment notes are internal. An insured claimant may see the
        # claim's public status and routing metadata, never the expert's
        # internal assessment narrative.
        description = (obj.assessment_note or "") if can_view_internal_notes else ""

    elif label == "claims.claimobjection":
        claim = obj.claim
        reference = claim.claim_number
        title = f"اعتراض به خسارت {claim.claim_number}"
        person_name = _text(getattr(claim, "person", None))
        company_name = _text(getattr(claim, "company_snapshot", None))
        _add(fields, "بیمه‌شده", person_name)
        _add(fields, "شرکت", company_name)
        _add(fields, "قرارداد", getattr(claim, "contract", None))
        _add(fields, "بیمه‌گر", getattr(claim, "insurer", None))
        _add(fields, "وضعیت اعتراض", obj.get_status_display())
        _add(fields, "مهلت پاسخ", obj.deadline_at)
        description = obj.description or ""

    elif label == "organizations.personchangerequest":
        reference = f"PC-{obj.pk}"
        title = f"اصلاح اطلاعات {obj.get_change_type_display()}"
        person_name = _text(obj.person)
        company_name = _text(obj.company)
        _add(fields, "بیمه‌شده", person_name)
        _add(fields, "شرکت در زمان درخواست", company_name)
        _add(fields, "قرارداد / بیمه‌گر مرتبط", obj.contract)
        _add(fields, "نوع تغییر", obj.get_change_type_display())
        _add(fields, "مقدار فعلی", obj.current_value)
        _add(fields, "مقدار درخواستی", obj.requested_value)
        _add(fields, "وضعیت", obj.get_status_display())
        description = obj.reason or ""

    elif label == "assets.insuredasset":
        reference = obj.asset_code
        title = obj.name
        _add(fields, "نوع دارایی", obj.get_asset_type_display())
        company_name = _text(getattr(obj, "company", None))
        person_name = _text(getattr(obj, "person", None))
        _add(fields, "شرکت", company_name)
        _add(fields, "بیمه‌شده مرتبط", person_name)
        _add(fields, "قرارداد", getattr(obj, "contract", None))
        _add(fields, "بیمه‌گر", getattr(obj, "insurer", None))
        _add(fields, "ارزش بیمه‌شده", obj.insured_value)
        _add(fields, "وضعیت", "فعال" if obj.is_active else "غیرفعال")
        description = obj.notes or ""

    elif label == "insurance.contractrevision":
        contract = obj.contract
        reference = contract.code
        title = contract.title
        _add(fields, "بیمه‌گر", contract.insurer)
        _add(fields, "رشته بیمه", contract.get_line_display())
        company_name = "، ".join(contract.companies.values_list("name", flat=True))
        _add(fields, "شرکت‌ها", company_name)
        _add(fields, "وضعیت نسخه", obj.get_status_display())
        _add(fields, "تاریخ اثر", obj.effective_date)
        _add(fields, "درخواست فسخ", "بله" if obj.is_termination else "خیر")
        description = obj.description or ""

    elif label == "correspondence.correspondence":
        reference = obj.internal_number
        title = obj.subject
        _add(fields, "جهت مکاتبه", obj.get_direction_display())
        _add(fields, "روش ارتباط", obj.get_channel_display())
        company_name = _text(getattr(obj, "company", None))
        _add(fields, "شرکت", company_name)
        _add(fields, "بیمه‌گر", getattr(obj, "insurer", None))
        _add(fields, "مسئول پیگیری", getattr(obj, "assigned_to", None))
        _add(fields, "وضعیت پیگیری", obj.get_follow_up_status_display())
        if not confidential:
            description = obj.summary or ""

    else:
        title = str(obj._meta.verbose_name)
        _add(fields, "نوع رکورد", obj._meta.label)
        _add(fields, "شناسه رکورد", obj.pk)

    # Former assignees retain a read-only timeline. Do not keep exposing
    # personal-change payloads or internal assessment narratives after handoff.
    if not is_current_owner and not can_view_confidential_content:
        description = ""
        if label == "organizations.personchangerequest":
            fields = [
                field for field in fields
                if field["label"] not in {"مقدار فعلی", "مقدار درخواستی", "دلیل و توضیحات"}
            ]

    return {
        "type_label": str(obj._meta.verbose_name),
        "reference": reference,
        "title": title,
        "company": company_name,
        "person": person_name,
        "fields": fields,
        "description": description,
        "is_confidential": confidential,
    }
