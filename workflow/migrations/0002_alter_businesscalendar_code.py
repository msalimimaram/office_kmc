from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="businesscalendar",
            name="code",
            field=models.SlugField(
                default="iran-default",
                max_length=80,
                unique=True,
                verbose_name="کد تقویم",
            ),
        ),
    ]
