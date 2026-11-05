from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class WorkflowDefinition(models.Model):
    code = models.SlugField("کد گردش کار", max_length=80)
    title = models.CharField("عنوان", max_length=180)
    version = models.PositiveIntegerField("نسخه", default=1)
    is_active = models.BooleanField("فعال", default=False)
    description = models.TextField("شرح", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="workflow_definitions_created")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="workflow_definitions_approved")
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("code", "-version")
        constraints = [
            models.UniqueConstraint(fields=("code", "version"), name="uniq_workflow_code_version"),
        ]
        verbose_name = "تعریف گردش کار"
        verbose_name_plural = "تعریف‌های گردش کار"

    def clean(self):
        super().clean()
        if self.is_active and not self.approved_by_id:
            raise ValidationError({"approved_by": "انتشار گردش کار نیازمند تأیید رئیس اداره یا مدیر سامانه است."})

    def save(self, *args, **kwargs):
        if self.is_active and not self.published_at:
            self.published_at = timezone.now()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} — v{self.version}"


class WorkflowStep(models.Model):
    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT, related_name="steps")
    code = models.SlugField("کد مرحله", max_length=60)
    title = models.CharField("عنوان مرحله", max_length=160)
    order = models.PositiveSmallIntegerField("ترتیب")
    allowed_roles = models.JSONField("نقش‌های مجاز", default=list, blank=True)
    sla_minutes = models.PositiveIntegerField("مهلت کاری (دقیقه)", default=0)
    is_initial = models.BooleanField("مرحله آغازین", default=False)
    is_terminal = models.BooleanField("مرحله پایانی", default=False)
    allow_return = models.BooleanField("امکان بازگشت", default=True)
    requires_acknowledgement = models.BooleanField("نیازمند تأیید رسمی مشاهده", default=False)

    class Meta:
        ordering = ("order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("definition", "code"), name="uniq_workflow_step_code"),
            models.UniqueConstraint(fields=("definition",), condition=models.Q(is_initial=True), name="uniq_workflow_initial_step"),
        ]
        verbose_name = "مرحله گردش کار"
        verbose_name_plural = "مراحل گردش کار"

    def clean(self):
        super().clean()
        if not isinstance(self.allowed_roles, list):
            raise ValidationError({"allowed_roles": "نقش‌های مجاز باید به صورت فهرست ذخیره شوند."})

    def __str__(self):
        return f"{self.definition.code}: {self.title}"


class WorkflowTransition(models.Model):
    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT, related_name="transitions")
    source_step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT, related_name="outgoing_transitions")
    target_step = models.ForeignKey(WorkflowStep, null=True, blank=True, on_delete=models.PROTECT, related_name="incoming_transitions")
    action_code = models.SlugField("کد اقدام", max_length=60)
    title = models.CharField("عنوان اقدام", max_length=120)
    allowed_roles = models.JSONField("نقش‌های مجاز برای اقدام", default=list, blank=True)
    recipient_roles = models.JSONField("نقش‌های مجاز گیرنده", default=list, blank=True)
    requires_note = models.BooleanField("توضیح اجباری", default=False)
    is_return = models.BooleanField("اقدام بازگشت", default=False)
    closes_case = models.BooleanField("بستن پرونده", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("source_step", "action_code"), name="uniq_workflow_action_per_step"),
        ]
        verbose_name = "مسیر انتقال"
        verbose_name_plural = "مسیرهای انتقال"

    def clean(self):
        super().clean()
        if self.source_step_id and self.source_step.definition_id != self.definition_id:
            raise ValidationError({"source_step": "مرحله مبدأ باید متعلق به همین تعریف باشد."})
        if self.target_step_id and self.target_step.definition_id != self.definition_id:
            raise ValidationError({"target_step": "مرحله مقصد باید متعلق به همین تعریف باشد."})
        if self.closes_case and self.target_step_id:
            raise ValidationError({"target_step": "مسیر بستن پرونده نباید مرحله مقصد داشته باشد."})

    def __str__(self):
        return f"{self.source_step} → {self.title}"


class WorkflowCase(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "باز"
        WAITING = "waiting", "در انتظار"
        COMPLETED = "completed", "تکمیل‌شده"
        CLOSED = "closed", "بسته‌شده"
        LOCKED = "locked", "قفل نهایی"

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT, related_name="cases")
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.PROTECT)
    object_id = models.CharField(max_length=64)
    content_object = models.GenericForeignKey("content_type", "object_id")
    current_step = models.ForeignKey(WorkflowStep, null=True, blank=True, on_delete=models.PROTECT, related_name="active_cases")
    current_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="workflow_cases")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(default=timezone.now)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    first_action_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="locked_workflow_cases")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("definition", "content_type", "object_id"), name="uniq_workflow_case_object"),
        ]
        indexes = [
            models.Index(fields=("current_assignee", "status"), name="workflow_assignee_status"),
            models.Index(fields=("content_type", "object_id"), name="workflow_object_lookup"),
        ]
        verbose_name = "پرونده گردش کار"
        verbose_name_plural = "پرونده‌های گردش کار"

    def __str__(self):
        return f"{self.definition.code} — {self.object_id}"


class WorkflowEvent(models.Model):
    class EventType(models.TextChoices):
        STARTED = "started", "شروع"
        OPENED = "opened", "مشاهده صفحه"
        ACKNOWLEDGED = "acknowledged", "تأیید رسمی مشاهده"
        ACTION = "action", "اقدام"
        REFERRED = "referred", "ارجاع"
        RETURNED = "returned", "بازگشت"
        LOCKED = "locked", "قفل نهایی"
        UNLOCKED = "unlocked", "رفع قفل"

    workflow_case = models.ForeignKey(WorkflowCase, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    action_code = models.CharField(max_length=60, blank=True)
    from_step = models.ForeignKey(WorkflowStep, null=True, blank=True, on_delete=models.PROTECT, related_name="events_from")
    to_step = models.ForeignKey(WorkflowStep, null=True, blank=True, on_delete=models.PROTECT, related_name="events_to")
    from_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="workflow_events_from")
    to_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="workflow_events_to")
    note = models.TextField(blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("sent_at", "pk")
        indexes = [models.Index(fields=("workflow_case", "sent_at"), name="workflow_event_timeline")]
        verbose_name = "رویداد گردش کار"
        verbose_name_plural = "تاریخچه گردش کار"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("رویداد گردش کار غیرقابل ویرایش است.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("رویداد گردش کار غیرقابل حذف است.")


class BusinessCalendar(models.Model):
    code = models.SlugField("کد تقویم", unique=True, default="iran-default")
    title = models.CharField("عنوان تقویم", max_length=120, default="تقویم کاری مجموعه")
    timezone_name = models.CharField(max_length=64, default="Asia/Tehran")
    working_weekdays = models.JSONField(default=list, help_text="روزهای هفته به صورت عدد 0 تا 6؛ دوشنبه=0")
    start_time = models.TimeField(default="08:00")
    end_time = models.TimeField(default="16:00")
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "تقویم کاری"
        verbose_name_plural = "تقویم‌های کاری"


class CalendarHoliday(models.Model):
    calendar = models.ForeignKey(BusinessCalendar, on_delete=models.PROTECT, related_name="holidays")
    date = models.DateField("تاریخ تعطیل")
    title = models.CharField("عنوان تعطیلی", max_length=180)
    is_working_override = models.BooleanField("روز کاری استثنایی", default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("calendar", "date"), name="uniq_calendar_holiday_date"),
        ]
        ordering = ("date",)
        verbose_name = "تعطیلی/استثنای تقویم"
        verbose_name_plural = "تعطیلی‌ها و استثناهای تقویم"
