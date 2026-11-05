import workflow.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.contrib.contenttypes.fields


def seed_default_calendar(apps, schema_editor):
    Calendar = apps.get_model("workflow", "BusinessCalendar")
    Calendar.objects.using(schema_editor.connection.alias).get_or_create(
        code="iran-default",
        defaults={"title": "تقویم کاری مجموعه", "timezone_name": "Asia/Tehran", "working_weekdays": [5, 6, 0, 1, 2, 3], "start_time": "08:00", "end_time": "16:00", "is_active": True},
    )


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessCalendar",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(default="iran-default", max_length=50, unique=True, verbose_name="کد تقویم")),
                ("title", models.CharField(default="تقویم کاری مجموعه", max_length=120, verbose_name="عنوان تقویم")),
                ("timezone_name", models.CharField(default="Asia/Tehran", max_length=64)),
                ("working_weekdays", models.JSONField(default=workflow.models.default_working_weekdays, help_text="روزهای هفته به صورت عدد 0 تا 6؛ دوشنبه=0")),
                ("start_time", models.TimeField(default="08:00")),
                ("end_time", models.TimeField(default="16:00")),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"verbose_name": "تقویم کاری", "verbose_name_plural": "تقویم‌های کاری"},
        ),
        migrations.CreateModel(
            name="WorkflowDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80, verbose_name="کد گردش کار")),
                ("title", models.CharField(max_length=180, verbose_name="عنوان")),
                ("version", models.PositiveIntegerField(default=1, verbose_name="نسخه")),
                ("is_active", models.BooleanField(default=False, verbose_name="فعال")),
                ("description", models.TextField(blank=True, verbose_name="شرح")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="workflow_definitions_approved", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="workflow_definitions_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "تعریف گردش کار", "verbose_name_plural": "تعریف‌های گردش کار", "ordering": ("code", "-version")},
        ),
        migrations.CreateModel(
            name="WorkflowStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=60, verbose_name="کد مرحله")),
                ("title", models.CharField(max_length=160, verbose_name="عنوان مرحله")),
                ("order", models.PositiveSmallIntegerField(verbose_name="ترتیب")),
                ("allowed_roles", models.JSONField(blank=True, default=list, verbose_name="نقش‌های مجاز")),
                ("sla_minutes", models.PositiveIntegerField(default=0, verbose_name="مهلت کاری (دقیقه)")),
                ("is_initial", models.BooleanField(default=False, verbose_name="مرحله آغازین")),
                ("is_terminal", models.BooleanField(default=False, verbose_name="مرحله پایانی")),
                ("allow_return", models.BooleanField(default=True, verbose_name="امکان بازگشت")),
                ("requires_acknowledgement", models.BooleanField(default=False, verbose_name="نیازمند تأیید رسمی مشاهده")),
                ("definition", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="steps", to="workflow.workflowdefinition")),
            ],
            options={"verbose_name": "مرحله گردش کار", "verbose_name_plural": "مراحل گردش کار", "ordering": ("order", "pk")},
        ),
        migrations.CreateModel(
            name="WorkflowTransition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_code", models.SlugField(max_length=60, verbose_name="کد اقدام")),
                ("title", models.CharField(max_length=120, verbose_name="عنوان اقدام")),
                ("allowed_roles", models.JSONField(blank=True, default=list, verbose_name="نقش‌های مجاز برای اقدام")),
                ("recipient_roles", models.JSONField(blank=True, default=list, verbose_name="نقش‌های مجاز گیرنده")),
                ("requires_note", models.BooleanField(default=False, verbose_name="توضیح اجباری")),
                ("is_return", models.BooleanField(default=False, verbose_name="اقدام بازگشت")),
                ("closes_case", models.BooleanField(default=False, verbose_name="بستن پرونده")),
                ("definition", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transitions", to="workflow.workflowdefinition")),
                ("source_step", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="outgoing_transitions", to="workflow.workflowstep")),
                ("target_step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="incoming_transitions", to="workflow.workflowstep")),
            ],
            options={"verbose_name": "مسیر انتقال", "verbose_name_plural": "مسیرهای انتقال"},
        ),
        migrations.CreateModel(
            name="WorkflowCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.CharField(max_length=64)),
                ("status", models.CharField(choices=[("open", "باز"), ("waiting", "در انتظار"), ("completed", "تکمیل‌شده"), ("closed", "بسته‌شده"), ("locked", "قفل نهایی")], default="open", max_length=16)),
                ("opened_at", models.DateTimeField(default=timezone.now)),
                ("first_viewed_at", models.DateTimeField(blank=True, null=True)),
                ("first_action_at", models.DateTimeField(blank=True, null=True)),
                ("sla_due_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("is_locked", models.BooleanField(default=False)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="contenttypes.contenttype")),
                ("current_assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="workflow_cases", to=settings.AUTH_USER_MODEL)),
                ("current_step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="active_cases", to="workflow.workflowstep")),
                ("definition", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cases", to="workflow.workflowdefinition")),
                ("locked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="locked_workflow_cases", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "پرونده گردش کار", "verbose_name_plural": "پرونده‌های گردش کار"},
        ),
        migrations.CreateModel(
            name="WorkflowEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("started", "شروع"), ("opened", "مشاهده صفحه"), ("acknowledged", "تأیید رسمی مشاهده"), ("action", "اقدام"), ("referred", "ارجاع"), ("returned", "بازگشت"), ("locked", "قفل نهایی"), ("unlocked", "رفع قفل")], max_length=20)),
                ("action_code", models.CharField(blank=True, max_length=60)),
                ("note", models.TextField(blank=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("acted_at", models.DateTimeField(blank=True, null=True)),
                ("sent_at", models.DateTimeField(default=timezone.now)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("from_assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="workflow_events_from", to=settings.AUTH_USER_MODEL)),
                ("from_step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="events_from", to="workflow.workflowstep")),
                ("to_assignee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="workflow_events_to", to=settings.AUTH_USER_MODEL)),
                ("to_step", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="events_to", to="workflow.workflowstep")),
                ("workflow_case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="workflow.workflowcase")),
            ],
            options={"verbose_name": "رویداد گردش کار", "verbose_name_plural": "تاریخچه گردش کار", "ordering": ("sent_at", "pk")},
        ),
        migrations.CreateModel(
            name="CalendarHoliday",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField(verbose_name="تاریخ تعطیل")),
                ("title", models.CharField(max_length=180, verbose_name="عنوان تعطیلی")),
                ("is_working_override", models.BooleanField(default=False, verbose_name="روز کاری استثنایی")),
                ("calendar", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="holidays", to="workflow.businesscalendar")),
            ],
            options={"verbose_name": "تعطیلی/استثنای تقویم", "verbose_name_plural": "تعطیلی‌ها و استثناهای تقویم", "ordering": ("date",)},
        ),
        migrations.AddConstraint(model_name="workflowdefinition", constraint=models.UniqueConstraint(fields=("code", "version"), name="uniq_workflow_code_version")),
        migrations.AddConstraint(model_name="workflowdefinition", constraint=models.UniqueConstraint(condition=models.Q(is_active=True), fields=("code",), name="uniq_active_workflow_code")),
        migrations.AddConstraint(model_name="workflowstep", constraint=models.UniqueConstraint(fields=("definition", "code"), name="uniq_workflow_step_code")),
        migrations.AddConstraint(model_name="workflowstep", constraint=models.UniqueConstraint(condition=models.Q(is_initial=True), fields=("definition",), name="uniq_workflow_initial_step")),
        migrations.AddConstraint(model_name="workflowtransition", constraint=models.UniqueConstraint(fields=("source_step", "action_code"), name="uniq_workflow_action_per_step")),
        migrations.AddConstraint(model_name="workflowcase", constraint=models.UniqueConstraint(fields=("definition", "content_type", "object_id"), name="uniq_workflow_case_object")),
        migrations.AddIndex(model_name="workflowcase", index=models.Index(fields=["current_assignee", "status"], name="workflow_assignee_status")),
        migrations.AddIndex(model_name="workflowcase", index=models.Index(fields=["content_type", "object_id"], name="workflow_object_lookup")),
        migrations.AddIndex(model_name="workflowevent", index=models.Index(fields=["workflow_case", "sent_at"], name="workflow_event_timeline")),
        migrations.AddConstraint(model_name="calendarholiday", constraint=models.UniqueConstraint(fields=("calendar", "date"), name="uniq_calendar_holiday_date")),
        migrations.RunPython(seed_default_calendar, migrations.RunPython.noop),
    ]
