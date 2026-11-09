from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models

from assets.models import AssetPolicyPeriod


class Command(BaseCommand):
    help = "Activate approved asset policy periods whose effective date has arrived."

    def handle(self, *args, **options):
        today = timezone.localdate()
        periods = AssetPolicyPeriod.objects.filter(
            status=AssetPolicyPeriod.Status.APPROVED,
        ).filter(
            models.Q(policy_start__isnull=True) | models.Q(policy_start__lte=today)
        ).select_related("asset", "insurer", "contract")
        activated = expired = 0
        for period in periods.iterator():
            if period.activate_if_due(on_date=today):
                if period.status == AssetPolicyPeriod.Status.ACTIVE:
                    activated += 1
                elif period.status == AssetPolicyPeriod.Status.EXPIRED:
                    expired += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Asset policy periods processed for {today}: "
                f"{activated} activated, {expired} expired."
            )
        )
