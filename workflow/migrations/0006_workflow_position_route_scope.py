from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0005_workflow_assignment_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtransition",
            name="position_route_scope",
            field=models.CharField(
                choices=[
                    ("line_wide", "تمام واحدهای همان رشته"),
                    ("same_unit", "همان واحد سازمانی"),
                    ("ancestors", "واحدهای بالادست"),
                    ("descendants", "واحدهای زیرمجموعه"),
                    ("related_units", "واحدهای مرتبط در همان شاخه"),
                ],
                default="related_units",
                help_text="برای گیرندگان سمت‌محور؛ علاوه بر رشته بیمه، ارتباط واحد سازمانی نیز کنترل می‌شود.",
                max_length=20,
                verbose_name="محدوده سازمانی گیرنده سمت‌محور",
            ),
        ),
    ]
