from django.db import migrations, models
import django.db.models.deletion


def backfill_person_relationships(apps, schema_editor):
    Person = apps.get_model("organizations", "Person")
    PersonRelationship = apps.get_model("organizations", "PersonRelationship")
    database = schema_editor.connection.alias

    for person in Person.objects.using(database).exclude(employee_id__isnull=True).iterator():
        PersonRelationship.objects.using(database).create(
            primary_person_id=person.employee_id,
            dependent_person_id=person.pk,
            relationship_type=person.relationship,
            status="active",
            # No relationship start date existed in the source schema.
            valid_from=None,
            valid_until=None,
            source_reference="migration:Person.employee",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0006_company_leadership_position_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonRelationship",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "relationship_type",
                    models.CharField(
                        choices=[
                            ("spouse", "همسر"),
                            ("child", "فرزند"),
                            ("father", "پدر"),
                            ("mother", "مادر"),
                            ("other", "سایر افراد تحت تکفل"),
                        ],
                        max_length=20,
                        verbose_name="نوع رابطه",
                    ),
                ),
                ("valid_from", models.DateField(blank=True, null=True, verbose_name="اعتبار از")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="اعتبار تا")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "معتبر"),
                            ("ended", "پایان‌یافته"),
                            ("voided", "ابطال‌شده"),
                        ],
                        default="active",
                        max_length=12,
                        verbose_name="وضعیت رابطه",
                    ),
                ),
                (
                    "source_reference",
                    models.CharField(blank=True, max_length=160, verbose_name="مرجع ایجاد رابطه"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
                (
                    "dependent_person",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="primary_relationships",
                        to="organizations.person",
                        verbose_name="فرد تحت تکفل",
                    ),
                ),
                (
                    "primary_person",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dependent_relationships",
                        to="organizations.person",
                        verbose_name="بیمه‌شده اصلی",
                    ),
                ),
            ],
            options={
                "verbose_name": "رابطه بیمه‌شده و فرد تحت تکفل",
                "verbose_name_plural": "روابط بیمه‌شدگان و افراد تحت تکفل",
                "ordering": ("dependent_person_id", "valid_from", "pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="personrelationship",
            constraint=models.CheckConstraint(
                condition=~models.Q(primary_person=models.F("dependent_person")),
                name="person_relationship_not_self",
            ),
        ),
        migrations.AddConstraint(
            model_name="personrelationship",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(valid_until__isnull=True)
                    | models.Q(valid_from__isnull=True)
                    | models.Q(valid_until__gte=models.F("valid_from"))
                ),
                name="person_relationship_dates_ordered",
            ),
        ),
        migrations.AddConstraint(
            model_name="personrelationship",
            constraint=models.UniqueConstraint(
                fields=("dependent_person",),
                condition=models.Q(status="active"),
                name="uniq_active_primary_per_dependent",
            ),
        ),
        migrations.AddIndex(
            model_name="personrelationship",
            index=models.Index(
                fields=["primary_person", "status", "valid_from"],
                name="person_rel_primary_state",
            ),
        ),
        migrations.AddIndex(
            model_name="personrelationship",
            index=models.Index(
                fields=["dependent_person", "status", "valid_until"],
                name="person_rel_dependent_state",
            ),
        ),
        migrations.RunPython(
            backfill_person_relationships,
            migrations.RunPython.noop,
        ),
    ]
