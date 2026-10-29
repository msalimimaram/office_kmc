from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from claims.models import Claim
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
from core.permissions import scoped_claims_for, scoped_requests_for


MANAGEMENT_ROLES = {"system_admin", "department_head"}


def _money(value: Decimal | None) -> Decimal:
    return value or Decimal("0")


def management_kpis(user) -> dict:
    """Build the management dashboard from the same scoped querysets used elsewhere."""
    if not (user.is_superuser or user.role in MANAGEMENT_ROLES):
        return {}

    claims = scoped_claims_for(user)
    requests = scoped_requests_for(user)
    people = Person.objects.filter(is_active=True, is_insured=True)

    total_claims = claims.count()
    paid_claims = claims.filter(status=Claim.Status.PAID).count()
    payable = _money(claims.aggregate(v=Sum("payable_amount"))["v"])
    paid = _money(claims.aggregate(v=Sum("paid_amount"))["v"])
    open_requests = requests.exclude(
        status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED, ServiceRequest.Status.REJECTED]
    )
    completed_requests = requests.filter(status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED])

    payment_rate = float((paid / payable) * 100) if payable else 0
    resolution_rate = (completed_requests.count() / requests.count() * 100) if requests.exists() else 0

    company_rows = (
        claims.values("person__company_id", "person__company__name")
        .annotate(claim_count=Count("id"), paid_amount=Sum("paid_amount"), payable_amount=Sum("payable_amount"))
        .order_by("-claim_count", "person__company__name")[:10]
    )
    ranking = [
        {
            "name": row["person__company__name"] or "بدون شرکت",
            "claim_count": row["claim_count"],
            "paid_amount": _money(row["paid_amount"]),
            "payable_amount": _money(row["payable_amount"]),
        }
        for row in company_rows
    ]

    status_rows = claims.values("status").annotate(count=Count("id")).order_by("-count")
    status_map = dict(Claim.Status.choices)
    status_breakdown = [
        {"label": status_map.get(row["status"], row["status"]), "count": row["count"]}
        for row in status_rows
    ]

    since = timezone.localdate().replace(day=1) - timedelta(days=180)
    monthly_rows = (
        claims.filter(registered_date__gte=since)
        .annotate(month=TruncMonth("registered_date"))
        .values("month")
        .annotate(count=Count("id"), payable=Sum("payable_amount"), paid=Sum("paid_amount"))
        .order_by("month")
    )
    monthly_map = OrderedDict()
    for row in monthly_rows:
        month = row["month"]
        key = month.strftime("%Y-%m") if month else "نامشخص"
        monthly_map[key] = {
            "label": key,
            "count": row["count"],
            "payable": _money(row["payable"]),
            "paid": _money(row["paid"]),
        }

    # The current model has no historical employee coverage table, so this is a
    # current-state operational KPI, not a historical headcount series.
    return {
        "insured_count": people.count(),
        "company_count": Company.objects.filter(is_active=True).count(),
        "claim_count": total_claims,
        "paid_claim_count": paid_claims,
        "payable_amount": payable,
        "paid_amount": paid,
        "payment_rate": round(payment_rate, 1),
        "request_count": requests.count(),
        "open_request_count": open_requests.count(),
        "resolution_rate": round(resolution_rate, 1),
        "ranking": ranking,
        "status_breakdown": status_breakdown,
        "monthly_trend": list(monthly_map.values()),
    }


def insured_dashboard_metrics(user) -> dict:
    """Compact, privacy-safe visual metrics for the insured dashboard."""
    claims = scoped_claims_for(user)
    requests = scoped_requests_for(user)
    claim_total = claims.count()
    paid = claims.filter(status=Claim.Status.PAID).count()
    pending = claims.exclude(status__in=[Claim.Status.PAID, Claim.Status.CLOSED, Claim.Status.REJECTED]).count()
    requests_open = requests.exclude(
        status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED, ServiceRequest.Status.REJECTED]
    ).count()
    return {
        "claim_total": claim_total,
        "claim_paid": paid,
        "claim_pending": pending,
        "request_open": requests_open,
        "claim_paid_ratio": round((paid / claim_total) * 100) if claim_total else 0,
    }
