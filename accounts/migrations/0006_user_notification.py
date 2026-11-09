from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_alter_user_managers_alter_user_company_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180, verbose_name="عنوان")),
                ("body", models.TextField(max_length=2000, verbose_name="متن اعلان")),
                ("target_url", models.CharField(blank=True, max_length=255, verbose_name="نشانی داخلی مقصد")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="زمان مشاهده")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="زمان ایجاد")),
                ("actor", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="notifications_created",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="ثبت‌کننده رویداد",
                )),
                ("recipient", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="notifications",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="دریافت‌کننده",
                )),
            ],
            options={
                "verbose_name": "اعلان کاربر",
                "verbose_name_plural": "اعلان‌های کاربران",
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddIndex(
            model_name="usernotification",
            index=models.Index(fields=["recipient", "read_at", "created_at"], name="user_notice_unread"),
        ),
    ]
