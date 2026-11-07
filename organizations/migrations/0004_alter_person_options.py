from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0003_unique_active_employment"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="person",
            options={
                "ordering": ["last_name", "first_name"],
                "verbose_name": "شخص",
                "verbose_name_plural": "اشخاص",
            },
        ),
    ]
