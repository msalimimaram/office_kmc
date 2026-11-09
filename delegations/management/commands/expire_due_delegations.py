from django.core.management.base import BaseCommand

from delegations.services import expire_due_delegations


class Command(BaseCommand):
    help = "Return open delegated cases to their delegators after delegation expiry."

    def handle(self, *args, **options):
        count = expire_due_delegations()
        self.stdout.write(self.style.SUCCESS(f"Expired delegations processed: {count}"))
