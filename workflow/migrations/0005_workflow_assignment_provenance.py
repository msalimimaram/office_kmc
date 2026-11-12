from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_notification"),
        ("workflow", "0004_workflow_position_eligibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowcase",
            name="current_position_assignment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="current_workflow_cases",
                to="accounts.positionassignment",
                verbose_name="انتصاب سمت مبنای مسئولیت جاری",
            ),
        ),
        migrations.AddField(
            model_name="workflowevent",
            name="from_position_assignment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_events_from",
                to="accounts.positionassignment",
                verbose_name="انتصاب سمت قبلی",
            ),
        ),
        migrations.AddField(
            model_name="workflowevent",
            name="to_position_assignment",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workflow_events_to",
                to="accounts.positionassignment",
                verbose_name="انتصاب سمت جدید",
            ),
        ),
    ]
