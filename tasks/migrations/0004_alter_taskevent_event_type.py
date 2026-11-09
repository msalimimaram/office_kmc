from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0003_alter_internaltask_options"),
    ]

    operations = [
        migrations.AlterField(
            model_name="taskevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("created", "ایجاد"),
                    ("assigned", "تخصیص"),
                    ("status", "تغییر وضعیت"),
                    ("comment", "یادداشت"),
                    ("due_changed", "تغییر مهلت"),
                    ("first_viewed", "اولین مشاهده"),
                    ("first_action", "اولین اقدام"),
                ],
                max_length=20,
            ),
        ),
    ]
