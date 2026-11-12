from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0006_workflow_position_route_scope"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowstep",
            name="allowed_roles",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="نقش‌های عملیاتی مجاز",
            ),
        ),
        migrations.AlterField(
            model_name="workflowtransition",
            name="allowed_roles",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="نقش‌های عملیاتی مجاز برای اقدام",
            ),
        ),
        migrations.AlterField(
            model_name="workflowtransition",
            name="recipient_roles",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="نقش‌های عملیاتی مجاز گیرنده",
            ),
        ),
    ]
