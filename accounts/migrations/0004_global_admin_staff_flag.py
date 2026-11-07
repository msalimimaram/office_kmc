from django.db import migrations


def grant_admin_site_access(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Assignment = apps.get_model("accounts", "RoleAssignment")
    database = schema_editor.connection.alias
    user_ids = Assignment.objects.using(database).filter(
        role__in=["system_admin", "department_head"], is_active=True
    ).values_list("user_id", flat=True).distinct()
    User.objects.using(database).filter(pk__in=user_ids).update(is_staff=True)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_role_assignment_foundation")]
    operations = [migrations.RunPython(grant_admin_site_access, migrations.RunPython.noop)]
