from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [("organizations", "0001_initial"), ("insurance", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Correspondence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("subject", models.CharField(max_length=250, verbose_name="موضوع")),
                ("channel", models.CharField(choices=[("email","ایمیل"),("phone","تلفن"),("meeting","جلسه"),("letter","نامه"),("portal","سامانه"),("other","سایر")], max_length=20, verbose_name="روش ارتباط")),
                ("direction", models.CharField(choices=[("inbound","دریافتی"),("outbound","ارسالی"),("internal","داخلی")], max_length=20, verbose_name="جهت مکاتبه")),
                ("external_reference", models.CharField(blank=True, max_length=120, verbose_name="شماره نامه/مرجع")),
                ("summary", models.TextField(verbose_name="خلاصه و اقدام انجام‌شده")),
                ("occurred_at", models.DateTimeField(verbose_name="زمان ارتباط")),
                ("follow_up_due", models.DateField(blank=True, null=True, verbose_name="مهلت پیگیری")),
                ("follow_up_status", models.CharField(choices=[("pending","در انتظار پیگیری"),("completed","پیگیری‌شده"),("not_required","نیازمند پیگیری نیست")], default="pending", max_length=20, verbose_name="وضعیت پیگیری")),
                ("is_confidential", models.BooleanField(default=False, verbose_name="محرمانه")),
                ("attachment", models.FileField(blank=True, upload_to="correspondence/", verbose_name="پیوست")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ثبت در سامانه")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین ویرایش")),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="correspondence", to="organizations.company")),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="correspondence", to="insurance.insurer")),
                ("contract", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="correspondence", to="insurance.contract")),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="assigned_correspondence", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_correspondence", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering":["follow_up_status","follow_up_due","-occurred_at"],"verbose_name":"مکاتبه","verbose_name_plural":"مکاتبات و پیگیری‌ها"},
        ),
    ]
