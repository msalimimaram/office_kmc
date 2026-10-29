from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth", "0012_alter_user_first_name_max_length"), ("organizations", "0001_initial"), ("insurance", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("password", models.CharField(max_length=128, verbose_name="password")),
                ("last_login", models.DateTimeField(blank=True, null=True, verbose_name="last login")),
                ("is_superuser", models.BooleanField(default=False, help_text="Designates that this user has all permissions without explicitly assigning them.", verbose_name="superuser status")),
                ("username", models.CharField(help_text="برای کاربران سازمانی از کد پرسنلی یکتا استفاده شود؛ از کد ملی به‌عنوان نام کاربری استفاده نکنید.", max_length=50, unique=True, verbose_name="نام کاربری")),
                ("first_name", models.CharField(blank=True, max_length=150, verbose_name="first name")),
                ("last_name", models.CharField(blank=True, max_length=150, verbose_name="last name")),
                ("email", models.EmailField(blank=True, max_length=254, verbose_name="email address")),
                ("is_staff", models.BooleanField(default=False, help_text="Designates whether the user can log into this admin site.", verbose_name="staff status")),
                ("is_active", models.BooleanField(default=True, help_text="Designates whether this user should be treated as active. Unselect this instead of deleting accounts.", verbose_name="active")),
                ("date_joined", models.DateTimeField(auto_now_add=True, verbose_name="date joined")),
                ("role", models.CharField(choices=[("system_admin","مدیر سامانه"),("department_head","رئیس اداره بیمه"),("insurance_specialist","کارشناس اداره بیمه"),("subsidiary_rep","نماینده شرکت تابعه"),("employee","بیمه‌شده"),("insurer","کارشناس بیمه‌گر"),("finance","واحد مالی"),("legal","واحد حقوقی"),("auditor","حسابرس")], default="employee", max_length=32, verbose_name="نقش")),
                ("mobile", models.CharField(blank=True, max_length=20, verbose_name="شماره همراه")),
                ("national_id", models.CharField(blank=True, db_index=True, max_length=10, verbose_name="کد ملی")),
                ("must_change_password", models.BooleanField(default=True, verbose_name="نیازمند تغییر رمز")),
                ("mfa_enabled", models.BooleanField(default=False, verbose_name="احراز هویت چندمرحله‌ای فعال")),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="organizations.company")),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="users", to="insurance.insurer", verbose_name="شرکت بیمه‌گر")),
                ("groups", models.ManyToManyField(blank=True, help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.", related_name="user_set", related_query_name="user", to="auth.group", verbose_name="groups")),
                ("user_permissions", models.ManyToManyField(blank=True, help_text="Specific permissions for this user.", related_name="user_set", related_query_name="user", to="auth.permission", verbose_name="user permissions")),
            ],
            options={"verbose_name":"user","verbose_name_plural":"users"},
        ),
    ]
