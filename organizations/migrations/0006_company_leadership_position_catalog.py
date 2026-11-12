from django.db import migrations, models
import django.db.models.deletion


def seed_company_positions(apps, schema_editor):
    Company = apps.get_model("organizations", "Company")
    Position = apps.get_model("organizations", "CompanyLeadershipPosition")
    Appointment = apps.get_model("organizations", "CompanyLeadershipTitle")
    defaults = [
        ("ceo", "مدیرعامل"),
        ("deputy_ceo", "قائم‌مقام مدیرعامل"),
        ("assistant_ceo", "معاون مدیرعامل"),
        ("board_chair", "رئیس هیئت‌مدیره"),
        ("board_member", "عضو هیئت‌مدیره"),
        ("director", "مدیر"),
    ]
    for company in Company.objects.all().iterator():
        for code, title in defaults:
            Position.objects.get_or_create(
                company_id=company.pk, code=code,
                defaults={"title": title, "is_active": True},
            )
        for appointment in Appointment.objects.filter(company_id=company.pk).iterator():
            position = Position.objects.filter(
                company_id=company.pk, title=appointment.title
            ).first()
            if position is None:
                position = Position.objects.create(
                    company_id=company.pk,
                    code=f"legacy-{appointment.pk}",
                    title=appointment.title,
                    is_active=True,
                )
            Appointment.objects.filter(pk=appointment.pk).update(position_id=position.pk)


class Migration(migrations.Migration):
    dependencies = [("organizations", "0005_person_change_request")]

    operations = [
        migrations.CreateModel(
            name="CompanyLeadershipPosition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=50, verbose_name="کد سمت")),
                ("title", models.CharField(max_length=150, verbose_name="عنوان سمت")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="leadership_position_options", to="organizations.company")),
            ],
            options={
                "verbose_name": "عنوان سمت مدیریتی شرکت",
                "verbose_name_plural": "فهرست سمت‌های مدیریتی شرکت‌ها",
                "ordering": ("company__name", "title"),
            },
        ),
        migrations.AddField(
            model_name="companyleadershiptitle",
            name="position",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="appointments", to="organizations.companyleadershipposition", verbose_name="عنوان سمت از فهرست شرکت"),
        ),
        migrations.AddConstraint(
            model_name="companyleadershipposition",
            constraint=models.UniqueConstraint(fields=("company", "code"), name="company_leadership_position_code_uniq"),
        ),
        migrations.AddConstraint(
            model_name="companyleadershipposition",
            constraint=models.UniqueConstraint(fields=("company", "title"), name="company_leadership_position_title_uniq"),
        ),
        migrations.RunPython(seed_company_positions, migrations.RunPython.noop),
    ]
