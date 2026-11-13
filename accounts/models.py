from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
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


class ProtectedAuthorizationAssignmentQuerySet(models.QuerySet):
    """Require authorization assignments to pass model validation on every write."""

    def update(self, **kwargs):
        raise ValidationError(
            "انتصاب‌های دسترسی فقط از مسیر ذخیره‌سازی اعتبارسنجی‌شده تغییر می‌کنند."
        )

    def bulk_create(self, objs, **kwargs):
        raise ValidationError(
            "ایجاد گروهی انتصاب دسترسی مجاز نیست؛ هر انتصاب باید جداگانه اعتبارسنجی شود."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(
            "ویرایش گروهی انتصاب دسترسی مجاز نیست؛ هر تغییر باید جداگانه اعتبارسنجی شود."
        )

    def delete(self):
        raise ValidationError(
            "سوابق انتصاب دسترسی حذف نمی‌شوند؛ دسترسی را با پایان اعتبار یا غیرفعال‌سازی خاتمه دهید."
        )


class RoleAssignment(models.Model):
    """Time-bounded, scoped operational authorization for a user."""

    objects = ProtectedAuthorizationAssignmentQuerySet.as_manager()

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

            if (
                self.is_active
                and self.user_id
                and self.company_id
                and self.valid_from
                and (self.valid_until is None or self.valid_until >= self.valid_from)
            ):
                previous = None
                if self.pk:
                    previous = type(self)._base_manager.filter(pk=self.pk).values(
                        "role", "user_id", "company_id", "line_code",
                        "valid_from", "valid_until", "is_active",
                        "reason", "approved_by_id",
                    ).first()

                scope_fields = (
                    "role", "user_id", "company_id", "valid_from",
                    "valid_until", "is_active",
                )
                approval_fields = scope_fields + (
                    "line_code", "reason", "approved_by_id",
                )
                scope_changed = previous is None or any(
                    previous[field] != getattr(self, field)
                    for field in scope_fields
                )
                approval_changed = previous is None or any(
                    previous[field] != getattr(self, field)
                    for field in approval_fields
                )

                overlapping = type(self)._base_manager.filter(
                    role=self.Role.SUBSIDIARY_REP,
                    is_active=True,
                    valid_from__lte=self.valid_until or date.max,
                ).filter(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_until__gte=self.valid_from)
                ).exclude(pk=self.pk)

                if scope_changed:
                    company_rows = list(
                        overlapping.filter(company_id=self.company_id).values(
                            "user_id", "valid_from", "valid_until",
                        )
                    )
                    change_points = {self.valid_from}
                    period_end = self.valid_until or date.max
                    for row in company_rows:
                        if self.valid_from < row["valid_from"] <= period_end:
                            change_points.add(row["valid_from"])
                        row_end = row["valid_until"]
                        if (
                            row_end is not None
                            and self.valid_from <= row_end < period_end
                        ):
                            change_points.add(row_end + timedelta(days=1))

                    exceeds_company_limit = False
                    for day in change_points:
                        active_users = {
                            row["user_id"]
                            for row in company_rows
                            if row["valid_from"] <= day
                            and (row["valid_until"] is None or row["valid_until"] >= day)
                        }
                        if self.user_id not in active_users and len(active_users) >= 3:
                            exceeds_company_limit = True
                            break
                    if exceeds_company_limit:
                        errors["company"] = (
                            "هر شرکت حداکثر سه نماینده فعال هم‌زمان می‌تواند داشته باشد."
                        )

                has_other_company_overlap = overlapping.filter(
                    user_id=self.user_id
                ).exclude(company_id=self.company_id).exists()
                if has_other_company_overlap and approval_changed:
                    if not self.reason.strip():
                        errors["reason"] = (
                            "برای نمایندگی هم‌زمان چند شرکت، ثبت دلیل استثنا الزامی است."
                        )
                    if not self.approved_by_id:
                        errors["approved_by"] = (
                            "نمایندگی هم‌زمان چند شرکت نیازمند تأیید مدیر سامانه است."
                        )
                    elif self.approved_by_id in {self.user_id, self.granted_by_id}:
                        errors["approved_by"] = (
                            "تأییدکننده باید مستقل از نماینده و ثبت‌کننده انتصاب باشد."
                        )
                    else:
                        from accounts.access import has_role
                        if not has_role(
                            self.approved_by,
                            self.Role.SYSTEM_ADMIN,
                        ):
                            errors["approved_by"] = (
                                "تأیید استثنای چندشرکتی فقط توسط مدیر سامانه فعال مجاز است."
                            )

                # A normal company representative must be an employee or a
                # registered dependent of that company for the full appointment
                # period. The approved multi-company exception is the only
                # cross-company bypass and remains explicitly time/reason bound.
                if not has_other_company_overlap and self.user_id and self.company_id:
                    from organizations.models import Person, PersonEmployment
                    linked_person = Person.objects.filter(user_id=self.user_id).select_related(
                        "employee"
                    ).first()
                    if linked_person:
                        if (
                            linked_person.relationship != Person.Relationship.EMPLOYEE
                            and not linked_person.employee_id
                        ):
                            errors["user"] = (
                                "نماینده‌ای که بیمه‌شده اصلی نیست باید به رابطه تحت تکفلِ کارمند اصلی متصل باشد."
                            )
                        primary_employee = linked_person.employee if linked_person.employee_id else linked_person
                        employment_rows = PersonEmployment.objects.filter(person_id=primary_employee.pk)
                        if employment_rows.exists():
                            assignment_end = self.valid_until or date.max
                            employment_covers_assignment = employment_rows.filter(
                                company_id=self.company_id,
                            ).filter(
                                models.Q(valid_from__isnull=True)
                                | models.Q(valid_from__lte=self.valid_from)
                            ).filter(
                                models.Q(valid_until__isnull=True)
                                | models.Q(valid_until__gte=assignment_end)
                            ).exists()
                            if not employment_covers_assignment:
                                errors["company"] = (
                                    "اعتبار نمایندگی باید به‌طور کامل داخل سابقه اشتغال معتبر بیمه‌شده اصلی در همان شرکت باشد."
                                )
                        elif primary_employee.company_id != self.company_id:
                            errors["company"] = (
                                "نماینده باید کارمند یا فرد تحت تکفلِ کارمند همان شرکت باشد."
                            )
                    elif self.user.company_id != self.company_id:
                        errors["company"] = (
                            "برای انتصاب نماینده، سابقه شخص/اشتغال همان شرکت یا پیوند سازمانی معتبر حساب کاربری الزامی است."
                        )
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
        with transaction.atomic():
            if self.role == self.Role.SUBSIDIARY_REP:
                User.objects.select_for_update().filter(pk=self.user_id).only("pk").first()
                if self.company_id:
                    company_model = self._meta.get_field("company").remote_field.model
                    company_model.objects.select_for_update().filter(
                        pk=self.company_id
                    ).only("pk").first()

            self.full_clean()
            result = super().save(*args, **kwargs)
            if self.role in {self.Role.SYSTEM_ADMIN, self.Role.DEPARTMENT_HEAD}:
                # is_staff is only Django's technical gate. Set it for any
                # scheduled global appointment; RestrictAdminAccessMiddleware
                # still checks the time-valid business role on every request.
                has_global_appointment = RoleAssignment.objects.filter(
                    user_id=self.user_id,
                    role__in={self.Role.SYSTEM_ADMIN, self.Role.DEPARTMENT_HEAD},
                    is_active=True,
                ).exists()
                if has_global_appointment:
                    User.objects.filter(pk=self.user_id, is_staff=False).update(is_staff=True)
            return result

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "سوابق انتصاب دسترسی حذف نمی‌شوند؛ دسترسی را با پایان اعتبار یا غیرفعال‌سازی خاتمه دهید."
        )

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

    objects = ProtectedAuthorizationAssignmentQuerySet.as_manager()

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
        if self.is_active and self.unit_id and not self.unit.is_active:
            raise ValidationError({"unit": "انتصاب فعال به واحد سازمانی غیرفعال مجاز نیست."})
        if self.is_active and self.position_id and not self.position.is_active:
            raise ValidationError({"position": "انتصاب فعال به سمت غیرفعال مجاز نیست."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.user_id:
                User.objects.select_for_update().filter(pk=self.user_id).only("pk").first()
            if self.unit_id:
                OrganizationalUnit.objects.select_for_update().filter(pk=self.unit_id).only("pk").first()
            if self.position_id:
                OrganizationalPosition.objects.select_for_update().filter(pk=self.position_id).only("pk").first()
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "سوابق انتصاب سمت حذف نمی‌شوند؛ دسترسی را با پایان اعتبار یا غیرفعال‌سازی خاتمه دهید."
        )

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
