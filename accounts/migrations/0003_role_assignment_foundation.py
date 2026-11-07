from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def migrate_legacy_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")
    database = schema_editor.connection.alias

    role_map = {
        "system_admin": ("system_admin", None),
        "department_head": ("department_head", None),
        "insurance_specialist": ("insurance_specialist", None),
        "subsidiary_rep": ("subsidiary_rep", "*"),
        "employee": ("insured_person", "*"),
        "insurer": ("insurer_representative", ""),
    }
    removed_roles = {"finance", "legal", "auditor"}

    for user in User.objects.using(database).all().iterator():
        legacy_role = str(user.role)
        if legacy_role in removed_roles:
            # Access is intentionally revoked; retain the account and all its history
            # for manual reassignment by an authorized administrator.
            User.objects.using(database).filter(pk=user.pk).update(is_active=False)
            continue

        mapped = role_map.get(legacy_role)
        if not mapped:
            continue

        new_role, line_code = mapped
        active = bool(user.is_active)
        reason = "ایجاد اولیه انتصاب از نقش قدیمی هنگام مهاجرت معماری چندنقشی"
        if legacy_role == "insurance_specialist":
            # A specialist must be assigned to an explicit insurance line.
            # The old model did not contain this information, so fail closed.
            active = False
            reason += "؛ نیازمند تعیین رشته بیمه توسط رئیس اداره یا مدیر سامانه"
        elif legacy_role == "subsidiary_rep" and not user.company_id:
            active = False
            reason += "؛ شرکت نماینده در داده قدیمی مشخص نشده است"
        elif legacy_role == "insurer" and not user.insurer_id:
            active = False
            reason += "؛ شرکت بیمه‌گر در داده قدیمی مشخص نشده است"
        elif legacy_role == "employee" and not user.national_id:
            active = False
            reason += "؛ کد ملی در حساب قدیمی ثبت نشده است"

        RoleAssignment.objects.using(database).get_or_create(
            user_id=user.pk,
            role=new_role,
            company_id=user.company_id if new_role == "subsidiary_rep" else None,
            insurer_id=user.insurer_id if new_role == "insurer_representative" else None,
            organizational_unit_id=None,
            position_id=None,
            line_code=line_code,
            valid_from=(user.date_joined.date() if user.date_joined else timezone.localdate()),
            valid_until=None,
            defaults={
                "is_active": active,
                "reason": reason,
                "granted_by_id": None,
                "approved_by_id": None,
            },
        )


def reverse_legacy_roles(apps, schema_editor):
    # The legacy role field is retained, so assignments can be removed on reverse.
    RoleAssignment = apps.get_model("accounts", "RoleAssignment")
    RoleAssignment.objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_fix_date_joined"),
        ("organizations", "0001_initial"),
        ("insurance", "0002_contractrevision"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationalUnit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True, verbose_name="کد واحد")),
                ("name", models.CharField(max_length=180, verbose_name="عنوان واحد")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("company", models.ForeignKey(blank=True, help_text="برای واحدهای اداره بیمه خالی؛ برای واحدهای وابسته به شرکت مشخص می‌شود.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="organizational_units", to="organizations.company")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="children", to="accounts.organizationalunit")),
            ],
            options={"verbose_name": "واحد سازمانی", "verbose_name_plural": "واحدهای سازمانی", "ordering": ("name", "pk")},
        ),
        migrations.CreateModel(
            name="OrganizationalPosition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, verbose_name="کد سمت")),
                ("title", models.CharField(max_length=120, verbose_name="عنوان سمت")),
                ("level", models.PositiveSmallIntegerField(choices=[(1, "معاونت"), (2, "مدیر"), (3, "رئیس"), (4, "سرپرست"), (5, "مسئول"), (6, "کارشناس")], verbose_name="سطح سلسله‌مراتب")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="positions", to="accounts.organizationalunit")),
            ],
            options={"verbose_name": "سمت سازمانی اداره", "verbose_name_plural": "سمت‌های سازمانی اداره", "ordering": ("level", "title")},
        ),
        migrations.CreateModel(
            name="RoleAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("system_admin", "مدیر سامانه"), ("department_head", "رئیس اداره بیمه"), ("insurance_specialist", "کارشناس اداره بیمه"), ("subsidiary_rep", "نماینده شرکت"), ("insurer_representative", "نماینده شرکت بیمه‌گر"), ("insured_person", "بیمه‌شده اصلی")], max_length=32, verbose_name="نقش عملیاتی")),
                ("line_code", models.CharField(blank=True, max_length=40, verbose_name="کد رشته بیمه")),
                ("valid_from", models.DateField(default=timezone.localdate, verbose_name="اعتبار از")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="اعتبار تا")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("reason", models.TextField(blank=True, verbose_name="دلیل انتصاب/تغییر")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_role_assignments", to=settings.AUTH_USER_MODEL)),
                ("company", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="role_assignments", to="organizations.company")),
                ("granted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="granted_role_assignments", to=settings.AUTH_USER_MODEL)),
                ("insurer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="role_assignments", to="insurance.insurer")),
                ("organizational_unit", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="role_assignments", to="accounts.organizationalunit")),
                ("position", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="role_assignments", to="accounts.organizationalposition")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="role_assignments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "انتصاب دسترسی", "verbose_name_plural": "انتصاب‌های دسترسی", "ordering": ("user_id", "role", "company_id", "insurer_id", "line_code", "valid_from")},
        ),
        migrations.CreateModel(
            name="PositionAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("line_code", models.CharField(blank=True, max_length=40, verbose_name="رشته بیمه")),
                ("valid_from", models.DateField(default=timezone.localdate, verbose_name="اعتبار از")),
                ("valid_until", models.DateField(blank=True, null=True, verbose_name="اعتبار تا")),
                ("is_active", models.BooleanField(default=True, verbose_name="فعال")),
                ("reason", models.TextField(blank=True, verbose_name="دلیل انتصاب")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="ایجاد")),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_position_assignments", to=settings.AUTH_USER_MODEL)),
                ("granted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="granted_position_assignments", to=settings.AUTH_USER_MODEL)),
                ("position", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="assignments", to="accounts.organizationalposition")),
                ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="position_assignments", to="accounts.organizationalunit")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="position_assignments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "انتصاب سمت", "verbose_name_plural": "انتصاب سمت‌ها", "ordering": ("unit_id", "position__level", "user_id")},
        ),
        migrations.AddConstraint(
            model_name="organizationalposition",
            constraint=models.UniqueConstraint(fields=("unit", "code"), name="uniq_position_code_per_unit"),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.CheckConstraint(condition=models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")), name="role_assignment_valid_dates"),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.CheckConstraint(condition=~models.Q(role="subsidiary_rep") | (models.Q(company__isnull=False) & models.Q(insurer__isnull=True)), name="role_assignment_company_scope"),
        ),
        migrations.AddConstraint(
            model_name="roleassignment",
            constraint=models.CheckConstraint(condition=~models.Q(role="insurer_representative") | (models.Q(insurer__isnull=False) & models.Q(company__isnull=True)), name="role_assignment_insurer_scope"),
        ),
        migrations.AddIndex(
            model_name="roleassignment",
            index=models.Index(fields=["user", "is_active", "valid_from", "valid_until"], name="role_user_active_dates"),
        ),
        migrations.AddIndex(
            model_name="roleassignment",
            index=models.Index(fields=["company", "role", "is_active"], name="role_company_lookup"),
        ),
        migrations.AddIndex(
            model_name="roleassignment",
            index=models.Index(fields=["insurer", "role", "is_active"], name="role_insurer_lookup"),
        ),
        migrations.AddConstraint(
            model_name="positionassignment",
            constraint=models.CheckConstraint(condition=models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=models.F("valid_from")), name="position_assignment_valid_dates"),
        ),
        migrations.RunPython(migrate_legacy_roles, reverse_legacy_roles),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("system_admin", "مدیر سامانه"),
                    ("department_head", "رئیس اداره بیمه"),
                    ("insurance_specialist", "کارشناس اداره بیمه"),
                    ("subsidiary_rep", "نماینده شرکت تابعه"),
                    ("employee", "بیمه‌شده"),
                    ("insurer", "نماینده شرکت بیمه‌گر"),
                ],
                default="employee",
                max_length=32,
                verbose_name="نقش قدیمی (سازگاری موقت)",
            ),
        ),
    ]
