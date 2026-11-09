from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verify that the core operational database tables have been created."

    REQUIRED_TABLES = (
        "announcements_announcement",
        "correspondence_correspondence",
        "correspondence_correspondencesequence",
        "correspondence_correspondencelink",
        "correspondence_correspondenceevent",
    )

    def handle(self, *args, **options):
        existing = set(connection.introspection.table_names())
        missing = [name for name in self.REQUIRED_TABLES if name not in existing]
        if missing:
            raise CommandError(
                "Required operational tables are missing: " + ", ".join(missing)
                + ". Run migrations and verify that both apps are installed."
            )
        self.stdout.write(self.style.SUCCESS(
            "PASS: announcements and correspondence tables exist: "
            + ", ".join(self.REQUIRED_TABLES)
        ))
