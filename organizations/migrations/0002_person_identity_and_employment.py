from collections import defaultdict

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.core.exceptions import ValidationError


DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)


def normalize_national_id(value):
    if value is None:
        return ""
    value = str(value).strip().translate(DIGIT_TRANSLATION)
    return "".join(char for char in value if char.isdigit())


def normalize_and_backfill(apps, schema_editor):
    Person = apps.get_model("organizations", "Person")
    PersonEmployment = apps.get_model("organizations", "PersonEmployment")
    User = apps.get_model("accounts", "User")
    db = schema_editor.connection.alias

    persons_by_national_id = defaultdict(list)
    invalid_persons = []
    for person in Person.objects.using(db).all().iterator():
        national_id = normalize_national_id(person.national_id)
        if len(national_id) != 10:
            invalid_persons.append((person.pk, person.national_id))
            continue
        persons_by_national_id[national_id].append(person.pk)

    duplicates = {
        national_id: ids
        for national_id, ids in persons_by_national_id.items()
        if len(ids) > 1
    }
    if invalid_persons or duplicates:
        details = []
        if invalid_persons:
            details.append("کد ملی نامعتبر برای Person: " + repr(invalid_persons[:30]))
        if duplicates:
            details.append("کد ملی تکراری در پرونده‌های اشخاص: " + repr(list(duplicates.items())[:30]))
        raise RuntimeError(
            "مهاجرت هویت متوقف شد تا داده‌ها به‌صورت دستی و بدون ادغام حدسی اصلاح شوند. "
            + " | ".join(details)
        )

    users_by_national_id = defaultdict(list)
    for user in User.objects.using(db).exclude(national_id="").iterator():
        national_id = normalize_national_id(user.national_id)
        if len(national_id) == 10:
            users_by_national_id[national_id].append(user.pk)

    duplicate_users = {
        national_id: ids
        for national_id, ids in users_by_national_id.items()
        if len(ids) > 1
    }
    if duplicate_users:
        raise RuntimeError(
            "مهاجرت هویت متوقف شد؛ بیش از یک حساب برای بعضی کدهای ملی وجود دارد: "
            + repr(list(duplicate_users.items())[:30])
        )

    for national_id, ids in persons_by_national_id.items():
        Person.objects.using(db).filter(pk=ids[0]).update(national_id=national_id)

    for national_id, user_ids in users_by_national_id.items():
        User.objects.using(db).filter(pk=user_ids[0]).update(national_id=national_id)
        person_ids = persons_by_national_id.get(national_id, [])
        if person_ids:
            person_id = person_ids[0]
            existing_user_link = Person.objects.using(db).filter(user_id=user_ids[0]).exclude(pk=person_id).exists()
            if existing_user_link:
                raise RuntimeError(
                    f"حساب کاربری {user_ids[0]} به بیش از یک پرونده شخص متصل می‌شود؛ مهاجرت متوقف شد."
                )
            Person.objects.using(db).filter(pk=person_id).update(user_id=user_ids[0])

    # Backfill the current employment snapshot only. Historical dates are unknown,
    # so valid_from deliberately remains NULL rather than inventing a start date.
    for person in Person.objects.using(db).filter(
        relationship="employee",
        company_id__isnull=False,
    ).iterator():
        PersonEmployment.objects.using(db).get_or_create(
            person_id=person.pk,
            company_id=person.company_id,
            valid_from__isnull=True,
            defaults={
                "valid_from": None,
                "valid_until": None,
                "personnel_code": person.personnel_code or "",
                "status": "active" if person.is_active else "terminated",
                "source_reference": "legacy_person_company_snapshot",
            },
        )


def reverse_backfill(apps, schema_editor):
    PersonEmployment = apps.get_model("organizations", "PersonEmployment")
    Person = apps.get_model("organizations", "Person")
    db = schema_editor.connection.alias
    PersonEmployment.objects.using(db).filter(
        source_reference="legacy_person_company_snapshot"
    ).delete()
    Person.objects.using(db).update(user=None)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
        ("accounts", "0003_role_assignment_foundation"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="birth_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ تولد"),
        ),
        migrations.AddField(
            model_name="person",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="person_record",
                to=settings.AUTH_USER_MODEL,
                verbose_name="حساب کاربری",
            ),
        ),
        migrations.AlterField(
            model_name="person",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="people",
                to="organizations.company",
            ),
        ),
        migrations.AlterField(
            model_name="person",
            name="relationship",
            field=models.CharField(
                choices=[
                    ("employee", "بیمه‌شده اصلی"),
                    ("spouse", "همسر"),
                    ("child", "فرزند"),
                    ("father", "پدر"),
                    ("mother", "مادر"),
                    ("other", "سایر افراد تحت تکفل"),
                ],
                default="employee",
                max_length=20,
                verbose_name="نسبت",
            ),
        ),
        migrations.CreateModel(
            name="PersonEmployment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("personnel_code", models.CharField(blank=True, db_index=True, max_length=50, verbose_name="کد پرسنلی در این شرکت")),
                ("job_title", models.CharField(blank=True, max_length=150, verbose_name="عنوان شغلی")),
                ("valid_from", models.DateField(blank=True, null=True, verbose_name="شروع اشتغال")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="پایان اشتغال")),
                ("status", models.CharField(choices=[("active", "شاغل"), ("transferred", "منتقل‌شده"), ("retired", "بازنشسته"), ("terminated", "خاتمه همکاری")], default="active", max_length=20, verbose_name="وضعیت اشتغال")),
                ("source_reference", models.CharField(blank=True, max_length=160, verbose_name="مرجع ورود اطلاعات")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_person_employments", to=settings.AUTH_USER_MODEL)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employments", to="organizations.company")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="created_person_employments", to=settings.AUTH_USER_MODEL)),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="employments", to="organizations.person")),
            ],
            options={"verbose_name": "سابقه اشتغال", "verbose_name_plural": "سوابق اشتغال", "ordering": ("person_id", "valid_from", "pk")},
        ),
        migrations.CreateModel(
            name="CompanyLeadershipTitle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=150, verbose_name="عنوان سمت")),
                ("valid_from", models.DateField(blank=True, null=True, verbose_name="اعتبار از")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="اعتبار تا")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ثبت")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="leadership_titles", to="organizations.company")),
                ("declared_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="declared_leadership_titles", to=settings.AUTH_USER_MODEL)),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="leadership_titles", to="organizations.person")),
            ],
            options={"verbose_name": "سمت مدیریتی اعلام‌شده شرکت", "verbose_name_plural": "سمت‌های مدیریتی اعلام‌شده شرکت", "ordering": ("company__name", "person__last_name", "title")},
        ),
        migrations.RemoveConstraint(
            model_name="person",
            name="uniq_person_company_national_id",
        ),
        migrations.RunPython(normalize_and_backfill, reverse_backfill),
        migrations.AlterField(
            model_name="person",
            name="national_id",
            field=models.CharField(db_index=True, max_length=10, unique=True, verbose_name="کد ملی"),
        ),
        migrations.AddConstraint(
            model_name="personemployment",
            constraint=models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_from__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="person_employment_dates_ordered",
            ),
        ),
        migrations.AddIndex(
            model_name="personemployment",
            index=models.Index(fields=["person", "company", "status"], name="employment_person_company"),
        ),
        migrations.AddIndex(
            model_name="personemployment",
            index=models.Index(fields=["company", "status", "valid_until"], name="employment_company_state"),
        ),
        migrations.AddConstraint(
            model_name="companyleadershiptitle",
            constraint=models.CheckConstraint(
                condition=models.Q(valid_until__isnull=True) | models.Q(valid_from__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")),
                name="leadership_title_dates_ordered",
            ),
        ),
    ]
