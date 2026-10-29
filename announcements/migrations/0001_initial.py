from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Announcement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=250, verbose_name="عنوان")),
                ("body", models.TextField(verbose_name="متن اطلاعیه")),
                ("audience", models.CharField(choices=[("all","همه کاربران"),("staff","اداره بیمه"),("subsidiary","نمایندگان شرکت‌ها"),("employees","کارکنان و بیمه‌شدگان"),("insurers","شرکت‌های بیمه‌گر"),("finance_legal","مالی و حقوقی")], default="all", max_length=20, verbose_name="مخاطب")),
                ("attachment", models.FileField(blank=True, upload_to="announcement_files/", verbose_name="پیوست")),
                ("is_published", models.BooleanField(default=False, verbose_name="منتشر شده")),
                ("publish_at", models.DateTimeField(verbose_name="زمان انتشار")),
                ("expires_at", models.DateTimeField(blank=True, null=True, verbose_name="پایان اعتبار")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="announcements", to="organizations.company")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.PROTECT if False else django.db.models.deletion.PROTECT, related_name="announcements", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["-publish_at","-created_at"],"verbose_name":"اطلاعیه","verbose_name_plural":"اطلاعیه‌ها و بخشنامه‌ها"},
        ),
    ]
