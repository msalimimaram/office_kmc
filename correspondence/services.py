from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
import jdatetime

from auditlog.services import record_event
from .models import Correspondence, CorrespondenceEvent, CorrespondenceSequence


def _solar_date(value):
    if value is None:
        value = timezone.now()
    if timezone.is_aware(value):
        local_day = timezone.localtime(value).date()
    else:
        local_day = value.date() if hasattr(value, "date") else value
    return jdatetime.date.fromgregorian(date=local_day).strftime("%Y%m%d")


@transaction.atomic
def next_internal_number(occurred_at=None):
    solar_day = _solar_date(occurred_at)
    try:
        sequence = CorrespondenceSequence.objects.select_for_update().get(solar_date=solar_day)
    except CorrespondenceSequence.DoesNotExist:
        try:
            with transaction.atomic():
                sequence = CorrespondenceSequence.objects.create(solar_date=solar_day, last_number=0)
        except IntegrityError:
            sequence = CorrespondenceSequence.objects.select_for_update().get(solar_date=solar_day)

    CorrespondenceSequence.objects.filter(pk=sequence.pk).update(last_number=F("last_number") + 1)
    sequence.refresh_from_db(fields=["last_number"])
    return f"{solar_day}{sequence.last_number:03d}"


@transaction.atomic
def create_correspondence(*, form, actor, request=None):
    item = form.save(commit=False)
    item.created_by = actor
    item.internal_number = next_internal_number(item.occurred_at)
    item.save()
    if hasattr(form, "save_m2m"):
        form.save_m2m()
    CorrespondenceEvent.objects.create(
        correspondence=item,
        actor=actor,
        event_type=CorrespondenceEvent.EventType.CREATED,
        summary="مکاتبه ثبت شد.",
        metadata={"internal_number": item.internal_number},
    )
    record_event(
        actor=actor,
        action="correspondence_created",
        obj=item,
        summary=f"مکاتبه با شماره {item.internal_number} ثبت شد.",
        after_data={
            "internal_number": item.internal_number,
            "direction": item.direction,
            "company_id": item.company_id,
            "insurer_id": item.insurer_id,
            "contract_id": item.contract_id,
        },
        request=request,
    )
    return item


@transaction.atomic
def add_correspondence_event(*, correspondence, actor, event_type, summary="", metadata=None, request=None):
    event = CorrespondenceEvent.objects.create(
        correspondence=correspondence,
        actor=actor,
        event_type=event_type,
        summary=summary,
        metadata=metadata or {},
    )
    record_event(
        actor=actor,
        action=f"correspondence_{event_type}",
        obj=correspondence,
        summary=summary or "رویداد مکاتبه ثبت شد.",
        after_data={"event_id": event.pk, "event_type": event_type, "metadata": metadata or {}},
        request=request,
    )
    return event
