from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batch_number", models.CharField(max_length=40, unique=True, verbose_name="شماره عملیات")),
                ("source_type", models.CharField(default="claims", max_length=50, verbose_name="نوع داده")),
                ("file", models.FileField(upload_to="imports/", verbose_name="فایل اکسل")),
                ("status", models.CharField(choices=[("uploaded","بارگذاری‌شده"),("validated","اعتبارسنجی‌شده"),("processed","پردازش‌شده"),("failed","ناموفق")], default="uploaded", max_length=16, verbose_name="وضعیت")),
                ("total_rows", models.PositiveIntegerField(default=0)),
                ("valid_rows", models.PositiveIntegerField(default=0)),
                ("invalid_rows", models.PositiveIntegerField(default=0)),
                ("result_report", models.TextField(blank=True, verbose_name="گزارش نتیجه")),
                ("preview_data", models.JSONField(blank=True, default=list, verbose_name="داده موقت پیش‌نمایش")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
