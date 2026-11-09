from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("insurance", "0003_contract_lifecycle"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="contractrevision",
            constraint=models.UniqueConstraint(
                condition=models.Q(status="pending_approval"),
                fields=("contract",),
                name="uniq_pending_contract_revision",
            ),
        ),
    ]
