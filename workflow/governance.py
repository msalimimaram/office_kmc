"""Authenticated proposal approval for versioned workflows."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import RoleAssignment
from auditlog.services import record_event
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
            **previous_data,
        },
        after_data={
            "is_active": True,
            "approved_by_id": approver.pk,
            "published_at": definition.published_at.isoformat() if definition.published_at else None,
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
