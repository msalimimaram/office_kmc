"""Company-scoped visibility for person records tied to historical employment periods.

A company may see person-owned assets and documents created during that person's
employment period at that company. A historic employment relationship alone is
not an enduring grant to all future personal records.
"""
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Coalesce

from .models import PersonEmployment


def records_in_company_employment_period(
    queryset,
    company_ids,
    *,
    person_field="person",
    timestamp_field="created_at",
):
    """Limit records to the matching employment period for their linked person.

    Records owned directly by a company should be handled by the caller through
    a direct company FK filter. This helper is for person-owned records.
    Dependents inherit the primary employee's employment history. Legacy
    Person.company pointers are used only when no employment history exists.
    """
    company_ids = tuple(company_ids or ())
    if not company_ids:
        return queryset.none()

    person_id = Coalesce(
        OuterRef(f"{person_field}__employee_id"),
        OuterRef(f"{person_field}_id"),
    )
    record_date = OuterRef(f"{timestamp_field}__date")

    matching_employment = PersonEmployment.objects.filter(
        person_id=person_id,
        company_id__in=company_ids,
    ).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=record_date)
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=record_date)
    )
    any_employment = PersonEmployment.objects.filter(person_id=person_id)

    return queryset.annotate(
        _company_employment_period_match=Exists(matching_employment),
        _person_has_employment_history=Exists(any_employment),
    ).filter(
        Q(_company_employment_period_match=True)
        | (
            Q(_person_has_employment_history=False)
            & Q(**{f"{person_field}__company_id__in": company_ids})
        )
    )
