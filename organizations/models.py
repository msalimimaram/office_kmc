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
    valid_from = models.DateField("اعتبار از", null=True, blank=True)
    valid_until = models.DateField("اعتبار تا", null=True, blank=True)
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



class ImmutablePersonChangeRequestQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("درخواست‌های تغییر اطلاعات از طریق update گروهی قابل تغییر نیستند.")

    def delete(self):
        raise ValidationError("حذف درخواست‌های تغییر اطلاعات مجاز نیست.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("ویرایش گروهی درخواست‌های تغییر اطلاعات مجاز نیست.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("ثبت گروهی درخواست‌های تغییر اطلاعات مجاز نیست.")


class PersonChangeRequest(models.Model):
    objects = ImmutablePersonChangeRequestQuerySet.as_manager()

    class ChangeType(models.TextChoices):
        MOBILE = "mobile", "شماره همراه"
        IBAN = "iban", "شماره شبا"
        NATIONAL_ID = "national_id", "کد ملی"
        FIRST_NAME = "first_name", "نام"
        LAST_NAME = "last_name", "نام خانوادگی"
        PERSONNEL_CODE = "personnel_code", "کد پرسنلی"
        BIRTH_DATE = "birth_date", "تاریخ تولد"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "ثبت‌شده"
        COMPANY_REVIEW = "company_review", "بررسی نماینده شرکت"
        INSURER_UPDATE = "insurer_update", "اقدام بیمه‌گر"
        COMPANY_FINAL_REVIEW = "company_final_review", "بازبینی نهایی نماینده شرکت"
        APPROVED = "approved", "تأیید و اعمال‌شده"
        REJECTED = "rejected", "ردشده"

    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="change_requests",
        verbose_name="شخص",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="person_change_requests",
        verbose_name="شرکت در زمان درخواست",
    )
    contract = models.ForeignKey(
        "insurance.Contract",
        on_delete=models.PROTECT,
        related_name="person_change_requests",
        verbose_name="قرارداد/بیمه‌گر مرتبط",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="person_change_requests",
        verbose_name="درخواست‌کننده",
    )
    change_type = models.CharField(
        "نوع تغییر",
        max_length=24,
        choices=ChangeType.choices,
    )
    current_value = models.CharField("مقدار ثبت‌شده هنگام درخواست", max_length=160, blank=True)
    requested_value = models.CharField("مقدار درخواستی", max_length=160)
    reason = models.TextField("دلیل و توضیحات", max_length=2000)
    status = models.CharField(
        "وضعیت",
        max_length=32,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_person_change_requests",
    )
    approved_at = models.DateTimeField("زمان تأیید نهایی", null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rejected_person_change_requests",
    )
    rejected_at = models.DateTimeField("زمان رد", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.UniqueConstraint(
                fields=("person", "change_type"),
                condition=models.Q(
                    status__in=[
                        "submitted",
                        "company_review",
                        "insurer_update",
                        "company_final_review",
                    ]
                ),
                name="uniq_open_person_change_field",
            ),
        ]
        indexes = [
            models.Index(fields=("company", "status", "created_at"), name="person_change_company_status"),
            models.Index(fields=("requested_by", "created_at"), name="person_change_requester"),
        ]
        verbose_name = "درخواست تغییر اطلاعات بیمه‌شده"
        verbose_name_plural = "درخواست‌های تغییر اطلاعات بیمه‌شدگان"

    FIELD_MAP = {
        ChangeType.MOBILE: "mobile",
        ChangeType.IBAN: "iban",
        ChangeType.NATIONAL_ID: "national_id",
        ChangeType.FIRST_NAME: "first_name",
        ChangeType.LAST_NAME: "last_name",
        ChangeType.PERSONNEL_CODE: "personnel_code",
        ChangeType.BIRTH_DATE: "birth_date",
    }

    def clean(self):
        super().clean()
        errors = {}
        field_name = self.FIELD_MAP.get(self.change_type)
        if not field_name:
            errors["change_type"] = "نوع تغییر انتخاب‌شده پشتیبانی نمی‌شود."
        if not (self.reason or "").strip() or len(self.reason.strip()) < 10:
            errors["reason"] = "شرح دلیل درخواست باید حداقل ۱۰ نویسه باشد."

        if self.person_id and self.requested_by_id:
            requester = self.requested_by
            person = self.person
            employee = person.employee if person.employee_id else person
            authorized = person.user_id == requester.pk or employee.user_id == requester.pk
            requester_national_id = normalize_national_id(getattr(requester, "national_id", ""))
            if requester_national_id and requester_national_id in {
                normalize_national_id(person.national_id),
                normalize_national_id(employee.national_id),
            }:
                authorized = True
            if not requester.is_active or not authorized:
                errors["requested_by"] = "درخواست باید توسط خود بیمه‌شده اصلی یا حساب کاربر او برای فرد تحت تکفل ثبت شود."

        if self.person_id and self.company_id:
            person = self.person
            employee = person.employee if person.employee_id else person
            today = timezone.localdate()
            active_employment = PersonEmployment.objects.filter(
                person_id=employee.pk,
                status=PersonEmployment.Status.ACTIVE,
            ).filter(
                models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today)
            ).filter(
                models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)
            ).order_by("-valid_from", "-pk").first()
            current_company_id = (
                active_employment.company_id if active_employment
                else employee.company_id if not PersonEmployment.objects.filter(person_id=employee.pk).exists()
                else None
            )
            if current_company_id != self.company_id:
                errors["company"] = "شرکت درخواست باید با محل اشتغال فعال شخص اصلی یکسان باشد."

        if self.contract_id and self.company_id:
            today = timezone.localdate()
            if not self.contract.companies.filter(pk=self.company_id).exists():
                errors["contract"] = "قرارداد انتخاب‌شده متعلق به شرکت این درخواست نیست."
            if (
                self.contract.status != "active"
                or not self.contract.is_active
                or self.contract.start_date > today
                or self.contract.end_date < today
            ):
                errors["contract"] = "فقط قرارداد فعال و معتبر در تاریخ درخواست قابل انتخاب است."

        value = (self.requested_value or "").strip()
        if not value:
            errors["requested_value"] = "مقدار جدید الزامی است."
        elif self.change_type == self.ChangeType.NATIONAL_ID:
            value = normalize_national_id(value)
            if len(value) != 10:
                errors["requested_value"] = "کد ملی باید دقیقاً ۱۰ رقم باشد."
        elif self.change_type == self.ChangeType.IBAN:
            value = "".join(value.upper().split())
            if len(value) != 26 or not value.startswith("IR") or not value[2:].isdigit():
                errors["requested_value"] = "شماره شبا باید با IR شروع شود و ۲۴ رقم داشته باشد."
        elif self.change_type == self.ChangeType.MOBILE:
            normalized = value.replace(" ", "").replace("-", "")
            digits = normalized[1:] if normalized.startswith("+") else normalized
            if not digits.isdigit() or not 8 <= len(digits) <= 15:
                errors["requested_value"] = "شماره همراه باید بین ۸ تا ۱۵ رقم معتبر باشد."
        elif self.change_type in {self.ChangeType.FIRST_NAME, self.ChangeType.LAST_NAME}:
            if len(value) > 100:
                errors["requested_value"] = "طول نام بیش از حد مجاز است."
        elif self.change_type == self.ChangeType.PERSONNEL_CODE and len(value) > 50:
            errors["requested_value"] = "طول کد پرسنلی بیش از حد مجاز است."
        elif self.change_type == self.ChangeType.BIRTH_DATE:
            from datetime import date

            try:
                parsed = date.fromisoformat(value)
                if parsed > timezone.localdate():
                    errors["requested_value"] = "تاریخ تولد نمی‌تواند در آینده باشد."
            except ValueError:
                errors["requested_value"] = "تاریخ تولد باید با قالب YYYY-MM-DD ثبت شود."
        if field_name and self.person_id:
            current = getattr(self.person, field_name)
            current_text = current.isoformat() if hasattr(current, "isoformat") else str(current or "")
            if current_text == value:
                errors["requested_value"] = "مقدار جدید با مقدار فعلی یکسان است."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            mutable = {"updated_at"}
            if getattr(self, "_workflow_status_update", False):
                mutable.update({
                    "status", "approved_by", "approved_at",
                    "rejected_by", "rejected_at",
                })
            changed = [
                field.name
                for field in self._meta.concrete_fields
                if field.name not in {"id"} | mutable
                and getattr(previous, field.attname) != getattr(self, field.attname)
            ]
            if changed:
                raise ValidationError("درخواست ثبت‌شده قابل ویرایش نیست؛ اطلاعات فقط از مسیر گردش کار تغییر می‌کند.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("درخواست تغییر اطلاعات حذف نمی‌شود؛ سوابق باید حفظ شوند.")

    def sync_workflow_status(self, *, step_code=None, closed=False, actor=None):
        terminal_decisions = {self.Status.APPROVED, self.Status.REJECTED}
        if closed and self.status == self.Status.COMPANY_FINAL_REVIEW:
            target = self.Status.APPROVED
        elif step_code in terminal_decisions:
            if not closed:
                return
            target = step_code
        elif step_code in dict(self.Status.choices):
            target = step_code
        else:
            return

        if self.status == target and (
            target != self.Status.APPROVED or self.approved_by_id == getattr(actor, "pk", None)
        ):
            return

        self.status = target
        update_fields = ["status", "updated_at"]
        if target == self.Status.APPROVED:
            self.approved_by = actor
            self.approved_at = timezone.now()
            update_fields.extend(["approved_by", "approved_at"])
        elif target == self.Status.REJECTED:
            self.rejected_by = actor
            self.rejected_at = timezone.now()
            update_fields.extend(["rejected_by", "rejected_at"])
        self._workflow_status_update = True
        try:
            self.save(update_fields=update_fields)
        finally:
            del self._workflow_status_update

        if target == self.Status.APPROVED:
            self.apply_approved_change(actor=actor)

    def apply_approved_change(self, *, actor):
        from django.contrib.auth import get_user_model
        from django.db import transaction
        from auditlog.services import record_event

        User = get_user_model()
        field_name = self.FIELD_MAP[self.change_type]
        with transaction.atomic():
            person = Person.objects.select_for_update().select_related("user").get(pk=self.person_id)
            current = getattr(person, field_name)
            current_text = current.isoformat() if hasattr(current, "isoformat") else str(current or "")
            if current_text != self.current_value:
                raise ValidationError(
                    "اطلاعات پایه پس از ثبت درخواست تغییر کرده است؛ این درخواست را رد و درخواست جدید ثبت کنید."
                )

            raw_value = self.requested_value.strip()
            if self.change_type == self.ChangeType.NATIONAL_ID:
                new_value = normalize_national_id(raw_value)
            elif self.change_type == self.ChangeType.IBAN:
                new_value = "".join(raw_value.upper().split())
            elif self.change_type == self.ChangeType.MOBILE:
                new_value = raw_value.replace(" ", "").replace("-", "")
            elif self.change_type == self.ChangeType.BIRTH_DATE:
                from datetime import date
                new_value = date.fromisoformat(raw_value)
            else:
                new_value = raw_value

            setattr(person, field_name, new_value)
            person.save(update_fields=[field_name, "updated_at"])

            if person.user_id:
                user = User.objects.select_for_update().get(pk=person.user_id)
                user_fields = []
                if self.change_type == self.ChangeType.NATIONAL_ID:
                    if User.objects.exclude(pk=user.pk).filter(username=new_value).exists():
                        raise ValidationError("کد ملی جدید قبلاً به‌عنوان نام کاربری ثبت شده است.")
                    if user.username != self.current_value:
                        raise ValidationError("نام کاربری حساب با کد ملی ثبت‌شده هم‌خوان نیست؛ اصلاح باید ابتدا توسط مدیر سامانه بررسی شود.")
                    user.username = new_value
                    user_fields.append("username")
                    user.national_id = new_value
                    user_fields.append("national_id")
                elif self.change_type == self.ChangeType.MOBILE:
                    user.mobile = new_value
                    user_fields.append("mobile")
                elif self.change_type == self.ChangeType.FIRST_NAME:
                    user.first_name = new_value
                    user_fields.append("first_name")
                elif self.change_type == self.ChangeType.LAST_NAME:
                    user.last_name = new_value
                    user_fields.append("last_name")
                if user_fields:
                    user.save(update_fields=user_fields)

            def audit_value(value):
                value = str(value or "")
                if self.change_type in {
                    self.ChangeType.MOBILE,
                    self.ChangeType.IBAN,
                    self.ChangeType.NATIONAL_ID,
                }:
                    return ("*" * max(0, len(value) - 4)) + value[-4:]
                return value

            record_event(
                actor=actor,
                action="person_change_approved",
                obj=person,
                summary=f"درخواست تغییر {self.get_change_type_display()} پس از تأیید نهایی اعمال شد.",
                before_data={field_name: audit_value(self.current_value)},
                after_data={field_name: audit_value(new_value)},
            )

    def __str__(self):
        return f"{self.person} · {self.get_change_type_display()} · {self.get_status_display()}"
