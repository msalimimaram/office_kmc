from django.db import migrations, models


LINES = (
    ("health", "درمان"),
    ("life", "عمر و حوادث"),
    ("liability", "مسئولیت"),
    ("fire", "آتش‌سوزی و اموال"),
    ("third_party", "شخص ثالث"),
    ("body", "بدنه خودرو"),
)


def seed_insurance_department_positions(apps, schema_editor):
    Unit = apps.get_model("accounts", "OrganizationalUnit")
    Position = apps.get_model("accounts", "OrganizationalPosition")
    database = schema_editor.connection.alias

    unit, _ = Unit.objects.using(database).get_or_create(
        code="insurance-department",
        defaults={"name": "اداره بیمه", "is_active": True},
    )
    if unit.company_id is not None:
        raise RuntimeError(
            "The reserved organizational unit code 'insurance-department' "
            "is already assigned to a company; resolve the collision before migration."
        )

    Position.objects.using(database).exclude(level=6).update(
        allow_multiple_holders=False
    )

    definitions = [("department-head", "رئیس اداره بیمه", 3, False)]
    for code, title in LINES:
        definitions.extend([
            (f"{code}-head", f"رئیس رشته {title}", 3, False),
            (f"{code}-supervisor", f"سرپرست رشته {title}", 4, False),
            (f"{code}-responsible", f"مسئول رشته {title}", 5, False),
            (f"{code}-specialist", f"کارشناس رشته {title}", 6, True),
        ])

    for code, title, level, allow_multiple in definitions:
        position, created = Position.objects.using(database).get_or_create(
            unit_id=unit.pk,
            code=code,
            defaults={
                "title": title,
                "level": level,
                "is_active": True,
                "allow_multiple_holders": allow_multiple,
            },
        )
        if not created and (
            position.title != title
            or position.level != level
            or position.allow_multiple_holders != allow_multiple
        ):
            raise RuntimeError(
                f"Reserved position code '{code}' already exists with different "
                "settings; resolve the collision before migration."
            )


def reverse_seed_insurance_department_positions(apps, schema_editor):
    # Preserve organization records and appointment history on reversal.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_notification"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationalposition",
            name="allow_multiple_holders",
            field=models.BooleanField(
                default=True,
                help_text="برای سمت‌های رئیس، سرپرست و مسئول، سیستم به‌صورت خودکار انتصاب هم‌زمان چند نفر را ممنوع می‌کند.",
                verbose_name="امکان انتصاب هم‌زمان چند نفر",
            ),
        ),
        migrations.RunPython(
            seed_insurance_department_positions,
            reverse_seed_insurance_department_positions,
        ),
    ]
