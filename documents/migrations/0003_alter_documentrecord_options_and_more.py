from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0002_versioning_and_confidentiality"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="documentrecord",
            options={
                "ordering": ("-created_at", "-pk"),
                "verbose_name": "پرونده سند",
                "verbose_name_plural": "پرونده‌های اسناد",
            },
        ),
        migrations.AlterField(
            model_name="documentrecord",
            name="file",
            field=models.FileField(upload_to="documents/", verbose_name="نسخه جاری سند"),
        ),
        migrations.AlterField(
            model_name="documentrecord",
            name="is_confidential",
            field=models.BooleanField(default=False, verbose_name="محرمانه (سازگاری قدیمی)"),
        ),
    ]
