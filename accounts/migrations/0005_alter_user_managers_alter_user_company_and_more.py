import django.contrib.auth.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_global_admin_staff_flag"),
        ("insurance", "0002_contractrevision"),
        ("organizations", "0002_person_identity_and_employment"),
    ]

    operations = [
        migrations.AlterModelManagers(
            name="user",
            managers=[
                ("objects", django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.AlterField(
            model_name="user",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="legacy_users",
                to="organizations.company",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="insurer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="legacy_users",
                to="insurance.insurer",
                verbose_name="شرکت بیمه‌گر",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="national_id",
            field=models.CharField(blank=True, db_index=True, max_length=10, verbose_name="کد ملی قدیمی"),
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("system_admin", "مدیر سامانه"),
                    ("department_head", "رئیس اداره بیمه"),
                    ("insurance_specialist", "کارشناس اداره بیمه"),
                    ("subsidiary_rep", "نماینده شرکت تابعه"),
                    ("employee", "بیمه‌شده"),
                    ("insurer", "نماینده شرکت بیمه‌گر"),
                ],
                default="employee",
                help_text="منبع نهایی مجوزدهی نیست؛ از انتصاب‌های معتبر استفاده می‌شود.",
                max_length=32,
                verbose_name="نقش قدیمی (سازگاری موقت)",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                help_text="برای بیمه‌شده اصلی کد ملی شناسه ورود است؛ حساب‌های سازمانی نیز باید به هویت معتبر متصل شوند.",
                max_length=50,
                unique=True,
                verbose_name="نام کاربری",
            ),
        ),
    ]
