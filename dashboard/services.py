from __future__ import annotations

from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from claims.models import Claim
from workflow.models import WorkflowCase, WorkflowEvent
from accounts.models import RoleAssignment, User
from organizations.models import Company, Person
from requests_portal.models import ServiceRequest
from accounts.access import has_global_access
from core.permissions import scoped_claims_for, scoped_requests_for


def _money(value: Decimal | None) -> Decimal:
    return value or Decimal("0")


def management_kpis(user) -> dict:
    """Build the management dashboard from the same scoped querysets used elsewhere."""
    if not has_global_access(user):
        return {}

    claims = scoped_claims_for(user)
    requests = scoped_requests_for(user)
    people = Person.objects.filter(is_active=True, is_insured=True)

    total_claims = claims.count()
    paid_claims = claims.filter(status=Claim.Status.PAID).count()
    payable = _money(claims.aggregate(v=Sum("payable_amount"))["v"])
    paid = _money(claims.aggregate(v=Sum("paid_amount"))["v"])
    open_requests = requests.exclude(status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED, ServiceRequest.Status.REJECTED])
    completed_requests = requests.filter(status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED])

    payment_rate = float((paid / payable) * 100) if payable else 0
    resolution_rate = (completed_requests.count() / requests.count() * 100) if requests.exists() else 0

    company_rows = (
        claims.values("company_snapshot_id", "company_snapshot__name")
        .annotate(claim_count=Count("id"), paid_amount=Sum("paid_amount"), payable_amount=Sum("payable_amount"))
        .order_by("-claim_count", "company_snapshot__name")[:10]
    )
    ranking = [
        {
            "name": row["company_snapshot__name"] or "شرکت نامشخص در زمان ثبت",
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
        monthly_map[key] = {"label": key, "count": row["count"], "payable": _money(row["payable"]), "paid": _money(row["paid"])}

    monthly_trend = list(monthly_map.values())
    max_monthly_count = max((row["count"] for row in monthly_trend), default=0)
    for row in monthly_trend:
        row["bar_percent"] = round((row["count"] / max_monthly_count) * 100) if max_monthly_count else 0

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
        "monthly_trend": monthly_trend,
    }


def insured_dashboard_metrics(user) -> dict:
    """Compact, privacy-safe visual metrics for the insured dashboard."""
    claims = scoped_claims_for(user)
    requests = scoped_requests_for(user)
    claim_total = claims.count()
    paid = claims.filter(status=Claim.Status.PAID).count()
    pending = claims.exclude(status__in=[Claim.Status.PAID, Claim.Status.CLOSED, Claim.Status.REJECTED]).count()
    requests_open = requests.exclude(status__in=[ServiceRequest.Status.COMPLETED, ServiceRequest.Status.CLOSED, ServiceRequest.Status.REJECTED]).count()
    return {
        "claim_total": claim_total,
        "claim_paid": paid,
        "claim_pending": pending,
        "request_open": requests_open,
        "claim_paid_ratio": round((paid / claim_total) * 100) if claim_total else 0,
    }


def personnel_performance_metrics(user, *, start_date=None, end_date=None) -> list[dict]:
    """Explainable staff workload and per-assignment response metrics."""
    if not has_global_access(user):
        return []
    from collections import defaultdict
    from datetime import timedelta
    from django.db.models import Q
    from django.utils import timezone

    today = timezone.localdate()
    end_date = min(end_date or today, today)
    start_date = min(start_date or (end_date - timedelta(days=30)), today)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    staff_ids = RoleAssignment.objects.filter(
        role=RoleAssignment.Role.INSURANCE_SPECIALIST,
        is_active=True,
        valid_from__lte=end_date,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=start_date)
    ).values_list("user_id", flat=True).distinct()
    people = User.objects.filter(pk__in=staff_ids).order_by(
        "last_name", "first_name", "username"
    )

    assignment_types = {
        WorkflowEvent.EventType.STARTED,
        WorkflowEvent.EventType.REFERRED,
        WorkflowEvent.EventType.RETURNED,
    }
    first_action_types = {
        WorkflowEvent.EventType.ACTION,
        WorkflowEvent.EventType.REFERRED,
        WorkflowEvent.EventType.RETURNED,
    }
    rows = []
    for person in people:
        active_cases = WorkflowCase.objects.filter(
            current_assignee=person,
            status__in=[WorkflowCase.Status.OPEN, WorkflowCase.Status.WAITING],
        )
        received_events = list(
            WorkflowEvent.objects.filter(
                to_assignee=person,
                event_type__in=assignment_types,
                sent_at__date__gte=start_date,
                sent_at__date__lte=end_date,
            ).order_by("sent_at", "pk")
        )
        case_ids = {event.workflow_case_id for event in received_events}
        events_by_case = defaultdict(list)
        if case_ids:
            all_case_events = WorkflowEvent.objects.filter(
                workflow_case_id__in=case_ids
            ).order_by("workflow_case_id", "sent_at", "pk")
            for event in all_case_events:
                events_by_case[event.workflow_case_id].append(event)

        view_latencies = []
        action_latencies = []
        for received in received_events:
            timeline = events_by_case[received.workflow_case_id]
            received_index = next(
                (index for index, event in enumerate(timeline) if event.pk == received.pk),
                None,
            )
            if received_index is None:
                continue
            segment_end = next(
                (
                    index for index in range(received_index + 1, len(timeline))
                    if timeline[index].event_type in assignment_types
                    and timeline[index].to_assignee_id is not None
                ),
                len(timeline),
            )
            segment = timeline[received_index + 1:segment_end + 1]
            first_view = next(
                (
                    event for event in segment
                    if event.event_type == WorkflowEvent.EventType.OPENED
                    and event.actor_id == person.pk
                ),
                None,
            )
            first_action = next(
                (
                    event for event in segment
                    if event.event_type in first_action_types
                    and event.actor_id == person.pk
                ),
                None,
            )
            if first_view:
                view_latencies.append(
                    max(0, (first_view.sent_at - received.sent_at).total_seconds() / 60)
                )
            if first_action:
                action_latencies.append(
                    max(0, (first_action.sent_at - received.sent_at).total_seconds() / 60)
                )

        events = WorkflowEvent.objects.filter(
            actor=person,
            sent_at__date__gte=start_date,
            sent_at__date__lte=end_date,
        )
        rows.append({
            "user": person,
            "active_cases": active_cases.count(),
            # Counts assignment episodes (initial receipt, referral, or return),
            # not just cases first created for this specialist.
            "initial_cases": len(received_events),
            "unique_received_cases": len(case_ids),
            "actions": events.filter(event_type=WorkflowEvent.EventType.ACTION).count(),
            "referrals": events.filter(event_type=WorkflowEvent.EventType.REFERRED).count(),
            "returns": events.filter(event_type=WorkflowEvent.EventType.RETURNED).count(),
            "first_views": len(view_latencies),
            "avg_first_view_minutes": (
                round(sum(view_latencies) / len(view_latencies), 1)
                if view_latencies else None
            ),
            "first_actions": len(action_latencies),
            "avg_first_action_minutes": (
                round(sum(action_latencies) / len(action_latencies), 1)
                if action_latencies else None
            ),
            "overdue": active_cases.filter(sla_due_at__lt=timezone.now()).count(),
        })
    return rows
