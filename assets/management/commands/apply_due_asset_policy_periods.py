from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models

from assets.models import AssetPolicyPeriod


class Command(BaseCommand):
    help = (
        "Expire ended active asset policy periods and activate approved periods "
        "whose effective date has arrived."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        expired_active = 0
        active_ids = AssetPolicyPeriod.objects.filter(
            status=AssetPolicyPeriod.Status.ACTIVE,
            policy_end__lt=today,
        ).values_list("pk", flat=True)
        for period_id in active_ids.iterator():
            period = AssetPolicyPeriod.objects.get(pk=period_id)
            if period.expire_if_due(on_date=today):
                expired_active += 1

        due_periods = AssetPolicyPeriod.objects.filter(
            status=AssetPolicyPeriod.Status.APPROVED,
        ).filter(
            models.Q(policy_start__isnull=True) | models.Q(policy_start__lte=today)
        ).select_related("asset", "insurer", "contract")
        activated = expired_approved = terminated = 0
        for period in due_periods.iterator():
            if period.activate_if_due(on_date=today):
                if period.status == AssetPolicyPeriod.Status.ACTIVE:
                    activated += 1
                elif period.status == AssetPolicyPeriod.Status.EXPIRED:
                    expired_approved += 1
                elif period.status == AssetPolicyPeriod.Status.TERMINATED:
                    terminated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Asset policy periods processed for {today}: "
                f"{expired_active} active periods expired, {activated} activated, "
                f"{expired_approved} already expired, {terminated} terminated by contract."
            )
        )
