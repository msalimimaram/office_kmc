from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from insurance.models import ContractRevision


class Command(BaseCommand):
    help = "Apply approved contract revisions whose effective date has arrived."

    def handle(self, *args, **options):
        today = timezone.localdate()
        due_ids = list(
            ContractRevision.objects.filter(
                status__in=[
                    ContractRevision.Status.APPROVED,
                    ContractRevision.Status.TERMINATED,
                ],
                applied_at__isnull=True,
                effective_date__lte=today,
            )
            .order_by("contract_id", "effective_date", "revision_number", "pk")
            .values_list("pk", flat=True)
        )
        applied = 0
        for revision_id in due_ids:
            try:
                with transaction.atomic():
                    revision = ContractRevision.objects.select_for_update().select_related(
                        "contract"
                    ).get(pk=revision_id)
                    if revision.applied_at or not revision.effective_date or revision.effective_date > today:
                        continue
                    revision.apply_to_contract()
                    applied += 1
            except Exception as exc:
                raise CommandError(
                    f"Applying contract revision {revision_id} failed; no partial transaction was kept: {exc}"
                ) from exc

        self.stdout.write(self.style.SUCCESS(
            f"{applied} approved contract revision(s) applied for {today.isoformat()}."
        ))
