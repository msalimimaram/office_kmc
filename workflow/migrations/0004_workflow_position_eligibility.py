from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0003_workflowcase_delegation"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowstep",
            name="allowed_position_levels",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="سطوح مجاز از ساختار سازمانی؛ همراه با محدوده رشته‌ای انتصاب بررسی می‌شوند.",
                verbose_name="سطوح سمت سازمانی مجاز",
            ),
        ),
        migrations.AddField(
            model_name="workflowtransition",
            name="allowed_position_levels",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="سطوح سمت سازمانی مجاز برای اقدام",
            ),
        ),
        migrations.AddField(
            model_name="workflowtransition",
            name="recipient_position_levels",
            field=models.JSONField(
                blank=True,
                default=list,
                verbose_name="سطوح سمت سازمانی مجاز گیرنده",
            ),
        ),
    ]
