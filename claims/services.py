from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.access import has_global_access, has_role, insurer_ids_for, line_codes_for
from accounts.models import RoleAssignment

from auditlog.services import record_event

from .models import Claim, ClaimPayment


def _net_paid(claim_id):
    entries = ClaimPayment.objects.filter(claim_id=claim_id)
    positive = entries.filter(entry_type=ClaimPayment.EntryType.PAYMENT).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    reversed_amount = entries.filter(entry_type=ClaimPayment.EntryType.REVERSAL).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return positive - reversed_amount


@transaction.atomic
def record_payment(
    *,
    claim_id,
    amount,
    paid_at=None,
    source_reference="",
    source_insurer=None,
    actor=None,
    confirmed_by=None,
    note="",
    request=None,
):
    claim = Claim.objects.select_for_update().select_related("contract").get(pk=claim_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise ValidationError("ثبت‌کننده پرداخت باید حساب فعال داشته باشد.")
    if not confirmed_by or not confirmed_by.is_authenticated or not confirmed_by.is_active or confirmed_by.pk == actor.pk:
        raise ValidationError("تأیید پرداخت باید توسط کاربر فعال و مستقل انجام شود.")
    line = claim.contract.line if claim.contract_id else "health"
    def authorized(user):
        if has_global_access(user):
            return True
        return has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line)
    if not authorized(actor) or not authorized(confirmed_by):
        raise ValidationError("ثبت و تأیید پرداخت فقط برای رئیس اداره، مدیر سامانه یا کارشناس مجاز همین رشته امکان‌پذیر است.")
    amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValidationError("مبلغ پرداخت باید عددی معتبر و بزرگ‌تر از صفر باشد.")
    if source_insurer and claim.insurer_id and source_insurer.pk != claim.insurer_id:
        raise ValidationError("بیمه‌گر اعلام‌کننده با بیمه‌گر خسارت یکسان نیست.")

    current_total = _net_paid(claim.pk)
    new_total = current_total + amount
    if new_total > claim.payable_amount:
        raise ValidationError("مجموع پرداخت‌ها نمی‌تواند از مبلغ قابل پرداخت بیشتر شود.")

    payment = ClaimPayment.objects.create(
        claim=claim,
        entry_type=ClaimPayment.EntryType.PAYMENT,
        amount=amount,
        paid_at=paid_at,
        source_reference=source_reference,
        source_insurer=source_insurer or claim.insurer,
        note=note,
        recorded_by=actor,
        confirmed_by=confirmed_by,
    )
    claim.paid_amount = new_total
    claim.payment_date = paid_at or claim.payment_date
    if new_total >= claim.payable_amount and claim.payable_amount > 0:
        claim.status = Claim.Status.PAID
    elif new_total > 0:
        claim.status = Claim.Status.PARTIALLY_PAID
    claim.save(update_fields=["paid_amount", "payment_date", "status", "updated_at"])

    record_event(
        actor=actor,
        action="claim_payment_recorded",
        obj=claim,
        summary="مرحله پرداخت خسارت ثبت شد.",
        after_data={
            "payment_id": payment.pk,
            "amount": str(amount),
            "net_paid_amount": str(new_total),
            "paid_at": paid_at.isoformat() if paid_at else None,
            "source_reference": source_reference,
        },
        request=request,
    )
    return payment


@transaction.atomic
def reverse_payment(
    *,
    payment_id,
    amount,
    actor,
    reason,
    confirmed_by,
    paid_at=None,
    request=None,
):
    original = ClaimPayment.objects.select_for_update().select_related("claim").get(
        pk=payment_id,
        entry_type=ClaimPayment.EntryType.PAYMENT,
    )
    claim = Claim.objects.select_for_update().select_related("contract").get(pk=original.claim_id)
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise ValidationError("ثبت‌کننده برگشت پرداخت باید حساب فعال داشته باشد.")
    if not confirmed_by or not confirmed_by.is_authenticated or not confirmed_by.is_active or confirmed_by.pk == actor.pk:
        raise ValidationError("تأیید برگشت باید توسط کاربر فعال و مستقل انجام شود.")
    line = claim.contract.line if claim.contract_id else "health"
    def authorized(user):
        if has_global_access(user):
            return True
        return has_role(user, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line)
    if not authorized(actor) or not authorized(confirmed_by):
        raise ValidationError("ثبت و تأیید برگشت فقط برای رئیس اداره، مدیر سامانه یا کارشناس مجاز همین رشته امکان‌پذیر است.")
    amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValidationError("مبلغ برگشتی باید عددی معتبر و بزرگ‌تر از صفر باشد.")
    if not reason.strip():
        raise ValidationError("علت برگشت پرداخت الزامی است.")

    already_reversed = ClaimPayment.objects.filter(
        reverses_payment=original,
        entry_type=ClaimPayment.EntryType.REVERSAL,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    if already_reversed + amount > original.amount:
        raise ValidationError("مبلغ برگشتی از مانده پرداخت اصلی بیشتر است.")

    reversal = ClaimPayment.objects.create(
        claim=claim,
        entry_type=ClaimPayment.EntryType.REVERSAL,
        amount=amount,
        paid_at=paid_at,
        source_reference=original.source_reference,
        source_insurer=original.source_insurer or claim.insurer,
        reverses_payment=original,
        note=reason,
        recorded_by=actor,
        confirmed_by=confirmed_by,
    )
    new_total = _net_paid(claim.pk)
    if new_total < 0:
        raise ValidationError("مجموع برگشت‌ها نمی‌تواند از پرداخت‌های ثبت‌شده بیشتر باشد.")
    claim.paid_amount = new_total
    claim.payment_date = paid_at or claim.payment_date
    if new_total >= claim.payable_amount and claim.payable_amount > 0:
        claim.status = Claim.Status.PAID
    elif new_total > 0:
        claim.status = Claim.Status.PARTIALLY_PAID
    elif claim.status in {Claim.Status.PAID, Claim.Status.PARTIALLY_PAID}:
        claim.status = Claim.Status.APPROVED
    claim.save(update_fields=["paid_amount", "payment_date", "status", "updated_at"])

    record_event(
        actor=actor,
        action="claim_payment_reversed",
        obj=claim,
        summary="برگشت/اصلاح مرحله پرداخت ثبت شد.",
        before_data={"paid_amount": str(new_total + amount)},
        after_data={
            "reversal_id": reversal.pk,
            "original_payment_id": original.pk,
            "amount": str(amount),
            "net_paid_amount": str(new_total),
            "reason": reason,
        },
        request=request,
    )
    return reversal

@transaction.atomic
def record_imported_payment(*, claim_id, amount, paid_at, source_reference, source_insurer, submitted_by, reviewed_by, note="", request=None):
    """Approve an insurer-reported payment without representing an actual money transfer."""
    claim = Claim.objects.select_for_update().select_related("contract").get(pk=claim_id)
    if not submitted_by or not submitted_by.is_authenticated or not submitted_by.is_active:
        raise ValidationError("ثبت‌کننده منبع باید حساب فعال داشته باشد.")
    if not reviewed_by or not reviewed_by.is_authenticated or not reviewed_by.is_active or reviewed_by.pk == submitted_by.pk:
        raise ValidationError("تأییدکننده باید کاربر فعال و مستقل از ثبت‌کننده منبع باشد.")
    if not has_role(submitted_by, RoleAssignment.Role.INSURER_REP):
        raise ValidationError("منبع این پرداخت باید نماینده بیمه‌گر باشد.")
    insurer_scope = insurer_ids_for(submitted_by)
    if len(insurer_scope) != 1 or claim.insurer_id not in insurer_scope:
        raise ValidationError("نماینده بیمه‌گر فقط می‌تواند پرداخت‌های بیمه‌گر متصل به حساب خود را اعلام کند.")
    line = claim.contract.line if claim.contract_id else "health"
    reviewer_allowed = has_global_access(reviewed_by) or has_role(
        reviewed_by, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line
    )
    if not reviewer_allowed:
        raise ValidationError("تأیید اطلاعات پرداخت فقط در اختیار رئیس اداره، مدیر سامانه یا کارشناس همان رشته است.")
    amount = Decimal(str(amount))
    if not amount.is_finite() or amount <= 0:
        raise ValidationError("مبلغ پرداخت باید عددی معتبر و بزرگ‌تر از صفر باشد.")
    if source_insurer and source_insurer.pk != claim.insurer_id:
        raise ValidationError("بیمه‌گر منبع با بیمه‌گر خسارت یکسان نیست.")
    total = _net_paid(claim.pk) + amount
    if total > claim.payable_amount:
        raise ValidationError("مجموع پرداخت‌ها از مبلغ قابل پرداخت بیشتر می‌شود.")
    payment = ClaimPayment.objects.create(
        claim=claim, entry_type=ClaimPayment.EntryType.PAYMENT, amount=amount,
        paid_at=paid_at, source_reference=source_reference,
        source_insurer=source_insurer or claim.insurer,
        note=note, recorded_by=submitted_by, confirmed_by=reviewed_by,
        is_legacy_import=True,
    )
    claim.paid_amount = total
    claim.payment_date = paid_at or claim.payment_date
    if total >= claim.payable_amount and claim.payable_amount > 0:
        claim.status = Claim.Status.PAID
    elif total > 0:
        claim.status = Claim.Status.PARTIALLY_PAID
    claim.save(update_fields=["paid_amount", "payment_date", "status", "updated_at"])
    record_event(
        actor=reviewed_by, action="claim_imported_payment_approved", obj=claim,
        summary="پرداخت اعلام‌شده توسط بیمه‌گر پس از بررسی تأیید شد.",
        after_data={"payment_id": payment.pk, "amount": str(amount), "net_paid_amount": str(total),
                    "submitted_by_id": submitted_by.pk, "source_reference": source_reference},
        request=request,
    )
    return payment
