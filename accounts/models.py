from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Authentication principal.

    The legacy role, company and insurer fields remain temporarily for
    compatibility while views are migrated to RoleAssignment. New permission
    checks must use the centralized accounts.access service.
    """

    class Role(models.TextChoices):
        SYSTEM_ADMIN = "system_admin", "مدیر سامانه"
        DEPARTMENT_HEAD = "department_head", "رئیس اداره بیمه"
        INSURANCE_SPECIALIST = "insurance_specialist", "کارشناس اداره بیمه"
        SUBSIDIARY_REP = "subsidiary_rep", "نماینده شرکت تابعه"
        EMPLOYEE = "employee", "بیمه‌شده"
        INSURER = "insurer", "نماینده شرکت بیمه‌گر"

    username = models.CharField(
        "نام کاربری",
        max_length=50,
        unique=True,
        help_text="برای بیمه‌شده اصلی کد ملی شناسه ورود است؛ حساب‌های سازمانی نیز باید به هویت معتبر متصل شوند.",
    )
    role = models.CharField(
        "نقش قدیمی (سازگاری موقت)",
        max_length=32,
        choices=Role.choices,
        default=Role.EMPLOYEE,
        help_text="منبع نهایی مجوزدهی نیست؛ از انتصاب‌های معتبر استفاده می‌شود.",
    )
    mobile = models.CharField("شماره همراه", max_length=20, blank=True)
    national_id = models.CharField("کد ملی قدیمی", max_length=10, blank=True, db_index=True)
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="legacy_users",
    )
    insurer = models.ForeignKey(
        "insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT,
        related_name="legacy_users", verbose_name="شرکت بیمه‌گر",
    )
    must_change_password = models.BooleanField("نیازمند تغییر رمز", default=True)
    mfa_enabled = models.BooleanField("احراز هویت چندمرحله‌ای فعال", default=False)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username


class OrganizationalUnit(models.Model):
    """A node in the insurance department's organization tree."""

    code = models.CharField("کد واحد", max_length=40, unique=True)
    name = models.CharField("عنوان واحد", max_length=180)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children",
    )
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="organizational_units",
        help_text="برای واحدهای اداره بیمه خالی؛ برای واحدهای وابسته به شرکت مشخص می‌شود.",
    )
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name = "واحد سازمانی"
        verbose_name_plural = "واحدهای سازمانی"

    def clean(self):
        super().clean()
        node = self.parent
        visited = {self.pk} if self.pk else set()
        while node is not None:
            if node.pk in visited:
                raise ValidationError({"parent": "ساختار واحدها نمی‌تواند چرخه داشته باشد."})
            visited.add(node.pk)
            if self.company_id and node.company_id and self.company_id != node.company_id:
                raise ValidationError({"parent": "واحد والد و فرزند باید در محدوده سازمانی یکسان باشند."})
            node = node.parent

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class OrganizationalPosition(models.Model):
    class Level(models.IntegerChoices):
        DEPUTY = 1, "معاونت"
        DIRECTOR = 2, "مدیر"
        HEAD = 3, "رئیس"
        SUPERVISOR = 4, "سرپرست"
        RESPONSIBLE = 5, "مسئول"
        SPECIALIST = 6, "کارشناس"

    unit = models.ForeignKey(OrganizationalUnit, on_delete=models.PROTECT, related_name="positions")
    code = models.CharField("کد سمت", max_length=40)
    title = models.CharField("عنوان سمت", max_length=120)
    level = models.PositiveSmallIntegerField("سطح سلسله‌مراتب", choices=Level.choices)
    is_active = models.BooleanField("فعال", default=True)

    class Meta:
        ordering = ("level", "title")
        constraints = [
            models.UniqueConstraint(fields=("unit", "code"), name="uniq_position_code_per_unit"),
        ]
        verbose_name = "سمت سازمانی اداره"
        verbose_name_plural = "سمت‌های سازمانی اداره"

    def __str__(self):
        return f"{self.title} — {self.unit.name}"


class RoleAssignment(models.Model):
    """Time-bounded, scoped operational authorization for a user."""

    class Role(models.TextChoices):
        SYSTEM_ADMIN = "system_admin", "مدیر سامانه"
        DEPARTMENT_HEAD = "department_head", "رئیس اداره بیمه"
        INSURANCE_SPECIALIST = "insurance_specialist", "کارشناس اداره بیمه"
        SUBSIDIARY_REP = "subsidiary_rep", "نماینده شرکت"
        INSURER_REP = "insurer_representative", "نماینده شرکت بیمه‌گر"
        INSURED_PERSON = "insured_person", "بیمه‌شده اصلی"

    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="role_assignments")
    role = models.CharField("نقش عملیاتی", max_length=32, choices=Role.choices)
    company = models.ForeignKey(
        "organizations.Company", null=True, blank=True, on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    insurer = models.ForeignKey(
        "insurance.Insurer", null=True, blank=True, on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    organizational_unit = models.ForeignKey(
        OrganizationalUnit, null=True, blank=True, on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    position = models.ForeignKey(
        OrganizationalPosition, null=True, blank=True, on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    # A concrete insurance-line code, or "*" for an explicitly all-line assignment.
    line_code = models.CharField("کد رشته بیمه", max_length=40, blank=True)
    valid_from = models.DateField("اعتبار از", default=timezone.localdate)
    valid_until = models.DateField("اعتبار تا", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    reason = models.TextField("دلیل انتصاب/تغییر", blank=True)
    granted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT,
        related_name="granted_role_assignments",
    )
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT,
        related_name="approved_role_assignments",
    )
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        ordering = ("user_id", "role", "company_id", "insurer_id", "line_code", "valid_from")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="role_assignment_valid_dates",
            ),
            models.CheckConstraint(
                condition=~models.Q(role="subsidiary_rep") | (
                    models.Q(company__isnull=False) & models.Q(insurer__isnull=True)
                ),
                name="role_assignment_company_scope",
            ),
            models.CheckConstraint(
                condition=~models.Q(role="insurer_representative") | (
                    models.Q(insurer__isnull=False) & models.Q(company__isnull=True)
                ),
                name="role_assignment_insurer_scope",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "is_active", "valid_from", "valid_until"), name="role_user_active_dates"),
            models.Index(fields=("company", "role", "is_active"), name="role_company_lookup"),
            models.Index(fields=("insurer", "role", "is_active"), name="role_insurer_lookup"),
        ]
        verbose_name = "انتصاب دسترسی"
        verbose_name_plural = "انتصاب‌های دسترسی"

    def clean(self):
        super().clean()
        errors = {}
        if self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = "پایان اعتبار نمی‌تواند قبل از شروع اعتبار باشد."
        if self.role == self.Role.SUBSIDIARY_REP:
            if not self.company_id:
                errors["company"] = "نماینده شرکت باید به یک شرکت مشخص متصل باشد."
            if self.insurer_id:
                errors["insurer"] = "انتصاب نماینده شرکت نمی‌تواند بیمه‌گر داشته باشد."
        elif self.role == self.Role.INSURER_REP:
            if not self.insurer_id:
                errors["insurer"] = "نماینده بیمه‌گر باید به یک شرکت بیمه مشخص متصل باشد."
            if self.company_id:
                errors["company"] = "انتصاب نماینده بیمه‌گر نمی‌تواند شرکت تابعه داشته باشد."
        elif self.role == self.Role.INSURANCE_SPECIALIST and self.is_active and not self.line_code:
            errors["line_code"] = "کارشناس فعال باید حداقل به یک رشته بیمه‌ای مشخص منتسب باشد."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        result = super().save(*args, **kwargs)
        if self.role in {self.Role.SYSTEM_ADMIN, self.Role.DEPARTMENT_HEAD}:
            today = timezone.localdate()
            active_global = RoleAssignment.objects.filter(user_id=self.user_id, role__in={self.Role.SYSTEM_ADMIN, self.Role.DEPARTMENT_HEAD}, is_active=True, valid_from__lte=today).filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)).exists()
            if active_global:
                User.objects.filter(pk=self.user_id, is_staff=False).update(is_staff=True)
        return result

    def is_valid_on(self, on_date=None):
        on_date = on_date or timezone.localdate()
        return (
            self.is_active
            and self.valid_from <= on_date
            and (self.valid_until is None or self.valid_until >= on_date)
        )

    def __str__(self):
        scope = self.company or self.insurer or self.organizational_unit or "سراسری"
        return f"{self.get_role_display()} — {self.user} — {scope}"


class PositionAssignment(models.Model):
    """Time-bounded position in the insurance department hierarchy."""

    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="position_assignments")
    unit = models.ForeignKey(OrganizationalUnit, on_delete=models.PROTECT, related_name="position_assignments")
    position = models.ForeignKey(OrganizationalPosition, on_delete=models.PROTECT, related_name="assignments")
    line_code = models.CharField("رشته بیمه", max_length=40, blank=True)
    valid_from = models.DateField("اعتبار از", default=timezone.localdate)
    valid_until = models.DateField("اعتبار تا", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    reason = models.TextField("دلیل انتصاب", blank=True)
    granted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT,
        related_name="granted_position_assignments",
    )
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT,
        related_name="approved_position_assignments",
    )
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        ordering = ("unit_id", "position__level", "user_id")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="position_assignment_valid_dates",
            ),
        ]
        verbose_name = "انتصاب سمت"
        verbose_name_plural = "انتصاب سمت‌ها"

    def clean(self):
        super().clean()
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "پایان اعتبار نمی‌تواند قبل از شروع باشد."})
        if self.position_id and self.unit_id and self.position.unit_id != self.unit_id:
            raise ValidationError({"position": "سمت انتخاب‌شده متعلق به واحد سازمانی دیگری است."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} — {self.position}"



class ImmutableUserNotificationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("اعلان‌های کاربر فقط از مسیر علامت‌گذاری به‌عنوان خوانده‌شده تغییر می‌کنند.")

    def delete(self):
        raise ValidationError("سوابق اعلان حذف نمی‌شوند.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی اعلان‌ها مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی اعلان‌ها مجاز نیست.")


class UserNotification(models.Model):
    objects = ImmutableUserNotificationQuerySet.as_manager()

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="notifications",
        verbose_name="دریافت‌کننده",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notifications_created",
        verbose_name="ثبت‌کننده رویداد",
    )
    title = models.CharField("عنوان", max_length=180)
    body = models.TextField("متن اعلان", max_length=2000)
    target_url = models.CharField("نشانی داخلی مقصد", max_length=255, blank=True)
    read_at = models.DateTimeField("زمان مشاهده", null=True, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=("recipient", "read_at", "created_at"), name="user_notice_unread"),
        ]
        verbose_name = "اعلان کاربر"
        verbose_name_plural = "اعلان‌های کاربران"

    def clean(self):
        super().clean()
        if self.target_url and (
            not self.target_url.startswith("/")
            or self.target_url.startswith("//")
            or "\\\" in self.target_url
        ):
            raise ValidationError({"target_url": "مقصد اعلان باید یک مسیر داخلی معتبر باشد."})

    def save(self, *args, **kwargs):
        if self.pk:
            update_fields = set(kwargs.get("update_fields") or ())
            if not update_fields or not update_fields.issubset({"read_at"}):
                raise ValidationError("اعلان پس از ثبت قابل ویرایش نیست.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("اعلان‌های ثبت‌شده حذف نمی‌شوند.")

    def mark_read(self, *, user):
        if self.recipient_id != user.pk:
            raise ValidationError("این اعلان متعلق به حساب کاربری شما نیست.")
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at"])

    @property
    def is_read(self):
        return self.read_at is not None

    def __str__(self):
        return f"{self.recipient} — {self.title}"
