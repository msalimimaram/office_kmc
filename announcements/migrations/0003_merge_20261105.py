from django.db import migrations


class Migration(migrations.Migration):
    # The two independent 0002 migrations were introduced on parallel
    # development paths. This merge node preserves both schema changes.
    dependencies = [
        ("announcements", "0002_align_defaults"),
        ("announcements", "0002_remove_finance_legal_audience"),
    ]

    operations = []
