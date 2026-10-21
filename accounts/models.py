from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = "system_admin", "مدیر سامانه"
        DEPARTMENT_HEAD = "department_head", "رئیس اداره بیمه"
        INSURANCE_SPECIALIST = "insurance_specialist", "کارشناس اداره بیمه"
        SUBSIDIARY_REP = "subsidiary_rep", "نماینده شرکت تابعه"
        EMPLOYEE = "employee", "بیمه‌شده"
        INSURER = "insurer", "کارشناس بیمه‌گر"
        FINANCE = "finance", "واحد مالی"
        LEGAL = "legal", "واحد حقوقی"
        AUDITOR = "auditor", "حسابرس"

    username = models.CharField(
        "نام کاربری", max_length=20, unique=True,
        help_text="برای کاربران سازمانی از کد پرسنلی یکتا استفاده شود؛ از کد ملی به‌عنوان نام کاربری استفاده نکنید.",
    )
    role = models.CharField("نقش", max_length=32, choices=Role.choices, default=Role.EMPLOYEE)
    mobile = models.CharField("شماره همراه", max_length=20, blank=True)
    national_id = models.CharField("کد ملی", max_length=10, blank=True, db_index=True)
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT, related_name="users"
    )
    must_change_password = models.BooleanField("نیازمند تغییر رمز", default=True)
    mfa_enabled = models.BooleanField("احراز هویت چندمرحله‌ای فعال", default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username
