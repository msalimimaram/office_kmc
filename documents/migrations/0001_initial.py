from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="DocumentRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=250, verbose_name="عنوان سند")),
                ("category", models.CharField(max_length=100, verbose_name="دسته")),
                ("file", models.FileField(upload_to="documents/", verbose_name="فایل اداری")),
                ("is_confidential", models.BooleanField(default=False, verbose_name="محرمانه")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="organizations.company")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
