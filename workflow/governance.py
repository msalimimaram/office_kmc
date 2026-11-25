"""Authenticated proposal approval for versioned workflows."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import RoleAssignment
from auditlog.services import record_event
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO
from .models import WorkflowDefinition


def has_active_governance_assignment(user, role):
    """Require an explicit, current, global governance assignment."""
    if (
        not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not getattr(user, "pk", None)
    ):
        return False
    today = timezone.localdate()
    return RoleAssignment.objects.filter(
        user_id=user.pk,
        role=role,
        is_active=True,
        valid_from__lte=today,
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=today)
    ).exists()


def build_workflow_snapshot(definition):
    """Return a JSON-safe, complete snapshot of a proposal's executable graph."""
    steps = list(definition.steps.order_by("order", "pk"))
    transitions = list(
        definition.transitions.select_related("source_step", "target_step").order_by(
            "source_step__order", "pk"
        )
    )
    return {
        "code": definition.code,
        "title": definition.title,
        "version": definition.version,
        "description": definition.description,
        "is_active": definition.is_active,
        "approved_by_id": definition.approved_by_id,
        "published_at": (
            definition.published_at.isoformat() if definition.published_at else None
        ),
        "steps": [
            {
                "code": step.code,
                "title": step.title,
                "order": step.order,
                "allowed_roles": list(step.allowed_roles or []),
                "allowed_position_levels": list(step.allowed_position_levels or []),
                "sla_minutes": step.sla_minutes,
                "is_initial": step.is_initial,
                "is_terminal": step.is_terminal,
                "allow_return": step.allow_return,
                "requires_acknowledgement": step.requires_acknowledgement,
            }
            for step in steps
        ],
        "transitions": [
            {
                "source_step": transition.source_step.code,
                "target_step": (
                    transition.target_step.code if transition.target_step_id else None
                ),
                "action_code": transition.action_code,
                "title": transition.title,
                "allowed_roles": list(transition.allowed_roles or []),
                "allowed_position_levels": list(transition.allowed_position_levels or []),
                "recipient_roles": list(transition.recipient_roles or []),
                "recipient_position_levels": list(transition.recipient_position_levels or []),
                "position_route_scope": transition.position_route_scope,
                "requires_note": transition.requires_note,
                "is_return": transition.is_return,
                "closes_case": transition.closes_case,
            }
            for transition in transitions
        ],
    }


@transaction.atomic
def approve_workflow_definition(*, definition_id, approver, request=None):
    """Approve and activate one draft using the authenticated Head's identity.

    Existing workflow cases are deliberately not migrated: they remain bound
    to the exact immutable version on which they were opened.
    """
    if not has_active_governance_assignment(
        approver, RoleAssignment.Role.DEPARTMENT_HEAD
    ):
        raise PermissionDenied("تأیید فقط برای رئیس اداره بیمه با انتصاب معتبر مجاز است.")

    definition = WorkflowDefinition.objects.select_for_update().get(
        pk=definition_id
    )
    if (
        definition.is_active
        or definition.published_at is not None
        or definition.approved_by_id is not None
    ):
        raise ValidationError("این پیشنهاد قبلاً تعیین تکلیف شده یا دیگر پیش‌نویس نیست.")

    if definition.created_by_id == approver.pk:
        raise PermissionDenied("ایجادکننده پیشنهاد مجاز به تأیید نسخه خود نیست.")

    if not has_active_governance_assignment(
        definition.created_by, RoleAssignment.Role.SYSTEM_ADMIN
    ):
        raise ValidationError(
            "پیشنهاددهنده باید در زمان تصویب، انتصاب فعال و معتبر مدیر سامانه داشته باشد."
        )

    steps = list(definition.steps.prefetch_related("outgoing_transitions"))
    initial_steps = [step for step in steps if step.is_initial]
    if len(initial_steps) != 1:
        raise ValidationError("نسخه پیشنهادی باید دقیقاً یک مرحله آغازین داشته باشد.")
    if not definition.transitions.exists():
        raise ValidationError("نسخه پیشنهادی باید حداقل یک مسیر انتقال معتبر داشته باشد.")
    disconnected = [
        step.code for step in steps
        if not step.is_terminal and not step.outgoing_transitions.exists()
    ]
    terminal_with_routes = [
        step.code for step in steps
        if step.is_terminal and step.outgoing_transitions.exists()
    ]
    if disconnected:
        raise ValidationError(
            "برای مراحل غیرپایانی مسیر خروجی تعریف نشده است: "
            + ", ".join(disconnected)
        )
    if terminal_with_routes:
        raise ValidationError(
            "مرحله پایانی نباید مسیر خروجی داشته باشد: "
            + ", ".join(terminal_with_routes)
        )

    # Reject unreachable states before approval, not only during the final
    # whole-catalog release audit.
    transitions = list(definition.transitions.select_related("source_step", "target_step"))
    reachable_ids = {initial_steps[0].pk}
    changed = True
    while changed:
        changed = False
        for transition in transitions:
            if (
                transition.source_step_id in reachable_ids
                and transition.target_step_id
                and transition.target_step_id not in reachable_ids
            ):
                reachable_ids.add(transition.target_step_id)
                changed = True
    unreachable = [
        step.code for step in steps if step.pk not in reachable_ids
    ]
    if unreachable:
        raise ValidationError(
            "مراحل زیر از مرحله آغازین قابل دسترسی نیستند: "
            + ", ".join(unreachable)
        )

    # Every operational stage must have a positive SLA explicitly confirmed
    # by a currently appointed Department Head. Seed values are examples only.
    unconfirmed_sla = [
        step.code for step in steps
        if not step.is_terminal
        and (
            step.sla_minutes <= 0
            or not step.sla_confirmed_by_id
            or not step.sla_confirmed_at
            or not has_active_governance_assignment(
                step.sla_confirmed_by, RoleAssignment.Role.DEPARTMENT_HEAD
            )
        )
    ]
    if unconfirmed_sla:
        raise ValidationError(
            "مهلت مراحل زیر هنوز توسط رئیس اداره بیمه تعیین و تأیید نشده است: "
            + ", ".join(unconfirmed_sla)
        )

    # Reuse the exact same domain-specific routing audit used for the
    # final catalog gate, scoped to this single draft before activation.
    audit_output = StringIO()
    try:
        call_command(
            "audit_workflows",
            definition_id=definition.pk,
            stdout=audit_output,
        )
    except CommandError as exc:
        details = audit_output.getvalue().strip()
        raise ValidationError(
            "ممیزی اختصاصی گردش‌کار ناموفق بود. "
            + details
            + (" " if details else "")
            + str(exc)
        ) from exc

    proposal_snapshot = build_workflow_snapshot(definition)

    previous_active = WorkflowDefinition.objects.select_for_update().filter(
        code=definition.code,
        is_active=True,
    ).exclude(pk=definition.pk).first()
    previous_data = {
        "active_version": previous_active.version if previous_active else None,
        "active_definition_id": previous_active.pk if previous_active else None,
    }

    # The unique active-version constraint requires retiring the previous
    # pointer first. Existing cases stay attached to their immutable version.
    if previous_active:
        previous_active.is_active = False
        previous_active.save(update_fields=["is_active"])

    definition.approved_by = approver
    definition.is_active = True
    definition.save()

    record_event(
        actor=approver,
        action="workflow.definition.approved_and_published",
        obj=definition,
        summary="رئیس اداره بیمه پیشنهاد گردش‌کار را تأیید و منتشر کرد.",
        before_data={
            "is_active": False,
            "approved_by_id": None,
            "workflow": proposal_snapshot,
            **previous_data,
        },
        after_data={
            "is_active": True,
            "approved_by_id": approver.pk,
            "published_at": definition.published_at.isoformat() if definition.published_at else None,
            "workflow": build_workflow_snapshot(definition),
        },
        metadata={
            "code": definition.code,
            "version": definition.version,
            "created_by_id": definition.created_by_id,
            "previous_active_definition_id": previous_data["active_definition_id"],
        },
        request=request,
    )
    return definition
