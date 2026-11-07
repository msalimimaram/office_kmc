from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_person_identity_and_employment"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="personemployment",
            constraint=models.UniqueConstraint(
                fields=("person",),
                condition=models.Q(status="active"),
                name="uniq_active_employment_per_person",
            ),
        ),
    ]
