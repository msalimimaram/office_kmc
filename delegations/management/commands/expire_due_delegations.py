from django.core.management.base import BaseCommand

from delegations.services import synchronize_delegations


class Command(BaseCommand):
    help = "Return open delegated cases to their delegators after delegation expiry."

    def handle(self, *args, **options):
        report = synchronize_delegations()
        self.stdout.write(self.style.SUCCESS(
            "Delegations synchronized: "
            f"expired={report['expired']}, suspended={report['suspended']}, "
            f"newly_routed={report['routed']}"
        ))
