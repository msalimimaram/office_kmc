import jdatetime

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def backfill_internal_numbers(apps, schema_editor):
    Correspondence = apps.get_model("correspondence", "Correspondence")
    Sequence = apps.get_model("correspondence", "CorrespondenceSequence")
    db = schema_editor.connection.alias
    counters = {}
    records = Correspondence.objects.using(db).order_by("occurred_at", "pk")
    for item in records.iterator():
        local_day = timezone.localtime(item.occurred_at).date()
        solar_day = jdatetime.date.fromgregorian(date=local_day).strftime("%Y%m%d")
        counters[solar_day] = counters.get(solar_day, 0) + 1
        item.internal_number = f"{solar_day}{counters[solar_day]:03d}"
        item.save(update_fields=["internal_number"])
    for solar_day, last_number in counters.items():
        Sequence.objects.using(db).update_or_create(
            solar_date=solar_day,
            defaults={"last_number": last_number},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("correspondence", "0002_align_defaults"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0003_role_assignment_foundation"),
    ]

    operations = [
        migrations.AddField(
            model_name="correspondence",
            name="internal_number",
            field=models.CharField(blank=True, max_length=20, null=True, verbose_name="شماره داخلی"),
        ),
        migrations.CreateModel(
            name="CorrespondenceSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("solar_date", models.CharField(max_length=8, unique=True, verbose_name="تاریخ شمسی فشرده")),
                ("last_number", models.PositiveIntegerField(default=0, verbose_name="آخرین شماره صادرشده")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "شمارنده شماره مکاتبات", "verbose_name_plural": "شمارنده‌های شماره مکاتبات", "ordering": ("-solar_date",)},
        ),
        migrations.CreateModel(
            name="CorrespondenceLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="contenttypes.contenttype")),
                ("correspondence", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="links", to="correspondence.correspondence")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "ارتباط مکاتبه", "verbose_name_plural": "ارتباط‌های مکاتبه"},
        ),
        migrations.CreateModel(
            name="CorrespondenceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("created", "ثبت مکاتبه"), ("referred", "ارجاع"), ("follow_up", "پیگیری"), ("response", "دریافت پاسخ"), ("status_changed", "تغییر وضعیت"), ("archived", "بایگانی")], max_length=20)),
                ("summary", models.TextField(blank=True, verbose_name="شرح اقدام")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(default=timezone.now)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("correspondence", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="correspondence.correspondence")),
            ],
            options={"verbose_name": "رویداد مکاتبه", "verbose_name_plural": "رویدادهای مکاتبه", "ordering": ("occurred_at", "pk")},
        ),
        migrations.RunPython(backfill_internal_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="correspondence",
            name="internal_number",
            field=models.CharField(blank=True, default="", max_length=20, unique=True, verbose_name="شماره داخلی"),
        ),
        migrations.AddConstraint(
            model_name="correspondencelink",
            constraint=models.UniqueConstraint(fields=("correspondence", "content_type", "object_id"), name="uniq_correspondence_link"),
        ),
        migrations.AddIndex(
            model_name="correspondencelink",
            index=models.Index(fields=["content_type", "object_id"], name="correspondence_link_target"),
        ),
    ]
