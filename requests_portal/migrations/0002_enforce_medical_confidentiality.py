from django.db import migrations, models


def enforce_medical_request_confidentiality(apps, schema_editor):
    ServiceRequest = apps.get_model("requests_portal", "ServiceRequest")
    ServiceRequest.objects.filter(kind="medical_assistance").update(is_confidential=True)


class Migration(migrations.Migration):
    dependencies = [
        ("requests_portal", "0001_initial"),
    ]

    operations = [
        # Backfill existing rows before applying the database-level invariant.
        migrations.RunPython(
            enforce_medical_request_confidentiality,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="servicerequest",
            constraint=models.CheckConstraint(
                condition=~models.Q(kind="medical_assistance") | models.Q(is_confidential=True),
                name="svc_medical_confidential",
            ),
        ),
    ]
