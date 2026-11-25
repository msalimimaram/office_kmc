# Department Head ownership and audit provenance for workflow SLA values.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0008_workflowsatisfactionsurvey"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowstep",
            name="sla_confirmed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_step_sla_confirmations",
                to=settings.AUTH_USER_MODEL,
                verbose_name="تعیین‌کننده مهلت",
            ),
        ),
        migrations.AddField(
            model_name="workflowstep",
            name="sla_confirmed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان تأیید مهلت"),
        ),
    ]
