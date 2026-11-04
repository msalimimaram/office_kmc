"""Structured append-only audit event creation."""
from __future__ import annotations

from uuid import UUID

from .models import AuditEvent


def client_ip(request):
    """Return the immediate peer address; do not trust forwarded headers by default."""
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def record_event(
    *,
    actor,
    action: str,
    obj=None,
    object_type: str | None = None,
    object_id: str | int | None = None,
    summary: str = "",
    before_data: dict | None = None,
    after_data: dict | None = None,
    metadata: dict | None = None,
    request=None,
    correlation_id: UUID | None = None,
) -> AuditEvent:
    """Record an immutable event with a minimal, structured change snapshot."""
    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id if object_id is not None else getattr(obj, "pk", "")
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=(object_type or "")[:120],
        object_id=str(object_id or "")[:100],
        summary=summary,
        before_data=before_data or {},
        after_data=after_data or {},
        metadata=metadata or {},
        ip_address=client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:512] if request else ""),
        correlation_id=correlation_id,
    )
