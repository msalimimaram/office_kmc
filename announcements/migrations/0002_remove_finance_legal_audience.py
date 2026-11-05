from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("announcements", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="announcement",
            name="audience",
            field=models.CharField(
                choices=[
                    ("all", "همه کاربران"),
                    ("staff", "اداره بیمه"),
                    ("subsidiary", "نمایندگان شرکت‌ها"),
                    ("employees", "کارکنان و بیمه‌شدگان"),
                    ("insurers", "شرکت‌های بیمه‌گر"),
                ],
                default="all",
                max_length=20,
                verbose_name="مخاطب",
            ),
        ),
    ]
