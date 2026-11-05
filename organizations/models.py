from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Company(models.Model):
    code = models.CharField("کد شرکت", max_length=30, unique=True)
    name = models.CharField("نام شرکت", max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="subsidiaries")
    is_parent = models.BooleanField("شرکت مادر", default=False)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "شرکت"
        verbose_name_plural = "شرکت‌ها"

    def clean(self):
        super().clean()
        node = self.parent
        visited = {self.pk} if self.pk else set()
        while node is not None:
            if node.pk in visited:
                raise ValidationError({"parent": "ساختار شرکت‌ها نمی‌تواند چرخه داشته باشد."})
            visited.add(node.pk)
            node = node.parent
        if self.parent_id == self.pk and self.pk:
            raise ValidationError({"parent": "یک شرکت نمی‌تواند والد خودش باشد."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Person(models.Model):
    class Relationship(models.TextChoices):
        EMPLOYEE = "employee", "بیمه‌شده اصلی"
        SPOUSE = "spouse", "همسر"
        CHILD = "child", "فرزند"
        FATHER = "father", "پدر"
        MOTHER = "mother", "مادر"
        OTHER = "other", "سایر افراد تحت تکفل"

    # Kept temporarily as the legacy/current company pointer. Historical
    # employment is stored in PersonEmployment and new code must use it.
    company = models.ForeignKey(
        Company, null=True, blank=True, on_delete=models.PROTECT, related_name="people",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="person_record", verbose_name="حساب کاربری",
    )
    personnel_code = models.CharField("کد پرسنلی", max_length=50, blank=True, db_index=True)
    national_id = models.CharField("کد ملی", max_length=10, unique=True, db_index=True)
    first_name = models.CharField("نام", max_length=100)
    last_name = models.CharField("نام خانوادگی", max_length=100)
    birth_date = models.DateField("تاریخ تولد", null=True, blank=True)
    relationship = models.CharField("نسبت", max_length=20, choices=Relationship.choices, default=Relationship.EMPLOYEE)
    employee = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="dependents")
    mobile = models.CharField("همراه", max_length=20, blank=True)
    iban = models.CharField("شماره شبا", max_length=34, blank=True)
    is_insured = models.BooleanField("تحت پوشش", default=True)
    is_active = models.BooleanField("فعال", default=True)
    updated_at = models.DateTimeField("آخرین بروزرسانی", auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "شخص"
        verbose_name_plural = "اشخاص"

    def clean(self):
        super().clean()
        errors = {}
        if self.employee_id and self.employee_id == self.pk:
            errors["employee"] = "یک شخص نمی‌تواند کارمند اصلی خودش باشد."
        if self.employee_id and self.relationship == self.Relationship.EMPLOYEE:
            errors["relationship"] = "شخص دارای کارمند اصلی باید نسبت تحت تکفل داشته باشد."
        if self._state.adding and not self.birth_date:
            errors["birth_date"] = "تاریخ تولد برای ثبت شخص الزامی است."
        if self.relationship == self.Relationship.EMPLOYEE and self.employee_id:
            errors["employee"] = "بیمه‌شده اصلی نباید به فرد دیگری وابسته باشد."
        if self.employee_id and self.company_id:
            today = timezone.localdate()
            active_employment = PersonEmployment.objects.filter(
                person_id=self.employee_id,
                status=PersonEmployment.Status.ACTIVE,
            ).filter(
                models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
            ).filter(
                models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
            ).order_by("-valid_from", "-pk").first()
            employee_company_id = (
                active_employment.company_id if active_employment
                else Person.objects.filter(pk=self.employee_id).values_list("company_id", flat=True).first()
            )
            if employee_company_id and employee_company_id != self.company_id:
                errors["company"] = "شرکت فرد تحت تکفل باید با شرکت محل اشتغال فعلی کارمند اصلی یکسان باشد."
        if self.national_id:
            normalized = normalize_national_id(self.national_id)
            if len(normalized) != 10:
                errors["national_id"] = "کد ملی باید دقیقاً ۱۰ رقم باشد."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.national_id = normalize_national_id(self.national_id)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class PersonEmployment(models.Model):
    """Historical employment of a person in a company; never overwrite old rows."""

    class Status(models.TextChoices):
        ACTIVE = "active", "شاغل"
        TRANSFERRED = "transferred", "منتقل‌شده"
        RETIRED = "retired", "بازنشسته"
        TERMINATED = "terminated", "خاتمه همکاری"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="employments")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="employments")
    personnel_code = models.CharField("کد پرسنلی در این شرکت", max_length=50, blank=True, db_index=True)
    job_title = models.CharField("عنوان شغلی", max_length=150, blank=True)
    valid_from = models.DateField("شروع اشتغال", null=True, blank=True)
    valid_until = models.DateField("پایان اشتغال", null=True, blank=True)
    status = models.CharField("وضعیت اشتغال", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    source_reference = models.CharField("مرجع ورود اطلاعات", max_length=160, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="created_person_employments")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_person_employments")
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        ordering = ("person_id", "valid_from", "pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_from__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="person_employment_dates_ordered",
            ),
            models.UniqueConstraint(fields=("person",), condition=models.Q(status="active"), name="uniq_active_employment_per_person"),
        ]
        indexes = [
            models.Index(fields=("person", "company", "status"), name="employment_person_company"),
            models.Index(fields=("company", "status", "valid_until"), name="employment_company_state"),
        ]
        verbose_name = "سابقه اشتغال"
        verbose_name_plural = "سوابق اشتغال"

    def clean(self):
        super().clean()
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "پایان اشتغال نمی‌تواند قبل از شروع باشد."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.person} — {self.company}"


class CompanyLeadershipTitle(models.Model):
    """Company-declared executive titles shown in the person's profile."""

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="leadership_titles")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="leadership_titles")
    title = models.CharField("عنوان سمت", max_length=150)
    valid_from = models.DateField("شروع اعتبار", null=True, blank=True)
    valid_until = models.DateField("پایان اعتبار", null=True, blank=True)
    declared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="declared_leadership_titles")
    created_at = models.DateTimeField("ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        ordering = ("company__name", "person__last_name", "title")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_from__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="leadership_title_dates_ordered",
            ),
        ]
        verbose_name = "سمت مدیریتی اعلام‌شده شرکت"
        verbose_name_plural = "سمت‌های مدیریتی اعلام‌شده شرکت"

    def clean(self):
        super().clean()
        errors = {}
        if not self.title.strip():
            errors["title"] = "عنوان سمت الزامی است."
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            errors["valid_until"] = "پایان اعتبار نمی‌تواند قبل از شروع باشد."
        if self.person_id and self.company_id:
            employed = PersonEmployment.objects.filter(person_id=self.person_id, company_id=self.company_id).filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.localdate())).exists()
            legacy_company_match = self.person.company_id == self.company_id
            if not employed and not legacy_company_match:
                errors["person"] = "این شخص در سوابق اشتغال به شرکت انتخاب‌شده متصل نیست."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — {self.person} — {self.company}"


def normalize_national_id(value: str) -> str:
    """Normalize Arabic/Persian digits and whitespace without guessing missing digits."""
    if value is None:
        return ""
    digits = str(value).strip()
    translation = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )
    digits = digits.translate(translation)
    return "".join(ch for ch in digits if ch.isdigit())
