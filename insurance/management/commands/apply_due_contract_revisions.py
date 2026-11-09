from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from insurance.models import Contract, ContractRevision


class Command(BaseCommand):
    help = "Apply due approved contract revisions and advance contract lifecycle dates."

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

        activated = 0
        expired = 0
        lifecycle_ids = list(
            Contract.objects.filter(
                status__in=[Contract.Status.APPROVED, Contract.Status.ACTIVE]
            ).values_list("pk", flat=True)
        )
        for contract_id in lifecycle_ids:
            with transaction.atomic():
                contract = Contract.objects.select_for_update().get(pk=contract_id)
                if contract.end_date < today:
                    target = Contract.Status.EXPIRED
                elif contract.start_date <= today <= contract.end_date:
                    target = Contract.Status.ACTIVE
                else:
                    target = Contract.Status.APPROVED
                if contract.status != target or contract.is_active != (target == Contract.Status.ACTIVE):
                    contract.status = target
                    contract.is_active = target == Contract.Status.ACTIVE
                    contract.save(update_fields=["status", "is_active"])
                    if target == Contract.Status.ACTIVE:
                        activated += 1
                    elif target == Contract.Status.EXPIRED:
                        expired += 1

        self.stdout.write(self.style.SUCCESS(
            f"{applied} revision(s) applied, {activated} contract(s) activated, "
            f"{expired} contract(s) expired for {today.isoformat()}."
        ))
