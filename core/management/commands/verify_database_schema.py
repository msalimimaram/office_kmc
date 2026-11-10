from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verify that every managed Django model and automatic many-to-many table exists."

    def handle(self, *args, **options):
        existing = set(connection.introspection.table_names())
        required = {
            model._meta.db_table
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy and not model._meta.swapped
        }
        missing = sorted(required - existing)
        if missing:
            raise CommandError(
                "Required Django model tables are missing: " + ", ".join(missing)
                + ". Run migrations and verify that all installed apps are synchronized."
            )
        self.stdout.write(self.style.SUCCESS(
            f"PASS: all {len(required)} managed model and many-to-many tables exist."
        ))
