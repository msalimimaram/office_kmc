from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("insurance", "0001_initial"), ("accounts", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="ContractRevision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision_number", models.PositiveIntegerField(verbose_name="شماره نسخه")),
                ("description", models.TextField(verbose_name="شرح تغییر")),
                ("document", models.FileField(blank=True, upload_to="contract_docs/", verbose_name="فایل سند غیرپزشکی")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("contract", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="revisions", to="insurance.contract")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="accounts.user")),
            ],
        ),
        migrations.AddConstraint(
            model_name="contractrevision",
            constraint=models.UniqueConstraint(fields=("contract","revision_number"), name="uniq_contract_revision"),
        ),
    ]
