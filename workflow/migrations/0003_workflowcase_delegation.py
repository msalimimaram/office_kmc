import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delegations", "0001_initial"),
        ("workflow", "0002_alter_businesscalendar_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowcase",
            name="delegation",
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="workflow_cases",
                to="delegations.workdelegation",
                verbose_name="تفویض اختیار مبنای ارجاع",
            ),
        ),
    ]
