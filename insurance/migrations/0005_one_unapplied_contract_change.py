from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insurance", "0004_one_pending_contract_revision"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="contractrevision",
            name="uniq_pending_contract_revision",
        ),
        migrations.AddConstraint(
            model_name="contractrevision",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    status__in=["pending_approval", "approved", "terminated"],
                    applied_at__isnull=True,
                ),
                fields=("contract",),
                name="uniq_unapplied_contract_revision",
            ),
        ),
    ]
