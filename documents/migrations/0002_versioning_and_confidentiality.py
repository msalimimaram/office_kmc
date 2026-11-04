from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_initial_versions(apps, schema_editor):
    DocumentRecord = apps.get_model("documents", "DocumentRecord")
    DocumentVersion = apps.get_model("documents", "DocumentVersion")
    db = schema_editor.connection.alias
    for document in DocumentRecord.objects.using(db).all().iterator():
        if document.file:
            DocumentVersion.objects.using(db).get_or_create(
                document_id=document.pk,
                version_number=1,
                defaults={
                    "file": document.file.name,
                    "uploaded_by_id": document.uploaded_by_id,
                    "change_reason": "نسخه اولیه منتقل‌شده از ساختار قبلی",
                    "is_current": True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("accounts", "0003_role_assignment_foundation"),
        ("organizations", "0002_person_identity_and_employment"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentrecord",
            name="person",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="organizations.person"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="security_level",
            field=models.CharField(choices=[("normal", "عادی"), ("internal", "داخلی"), ("confidential", "محرمانه"), ("very_confidential", "بسیار محرمانه")], default="normal", max_length=24, verbose_name="سطح محرمانگی"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="is_medical",
            field=models.BooleanField(default=False, verbose_name="سند پزشکی"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="is_archived",
            field=models.BooleanField(default=False, verbose_name="بایگانی شده"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان بایگانی"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="archive_reason",
            field=models.TextField(blank=True, verbose_name="دلیل بایگانی"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="is_void",
            field=models.BooleanField(default=False, verbose_name="باطل شده"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان ابطال"),
        ),
        migrations.AddField(
            model_name="documentrecord",
            name="void_reason",
            field=models.TextField(blank=True, verbose_name="دلیل ابطال"),
        ),
        migrations.AlterField(
            model_name="documentrecord",
            name="uploaded_by",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="uploaded_documents", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="documentrecord",
            name="company",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="documents", to="organizations.company"),
        ),
        migrations.CreateModel(
            name="DocumentVersion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version_number", models.PositiveIntegerField(verbose_name="شماره نسخه")),
                ("file", models.FileField(upload_to="document_versions/", verbose_name="فایل نسخه")),
                ("change_reason", models.TextField(blank=True, verbose_name="شرح تغییر")),
                ("checksum_sha256", models.CharField(blank=True, max_length=64, verbose_name="SHA256")),
                ("is_current", models.BooleanField(default=True, verbose_name="نسخه جاری")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="versions", to="documents.documentrecord")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="document_versions_uploaded", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "نسخه سند", "verbose_name_plural": "نسخه‌های سند", "ordering": ("document_id", "-version_number")},
        ),
        migrations.CreateModel(
            name="DocumentLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="contenttypes.contenttype")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="links", to="documents.documentrecord")),
            ],
            options={"verbose_name": "ارتباط سند", "verbose_name_plural": "ارتباط‌های سند"},
        ),
        migrations.CreateModel(
            name="DocumentAccessEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("view", "مشاهده"), ("download", "دریافت"), ("print", "چاپ"), ("export", "خروجی")], max_length=12)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("document", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="access_events", to="documents.documentrecord")),
                ("version", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="access_events", to="documents.documentversion")),
            ],
            options={"verbose_name": "رویداد دسترسی سند", "verbose_name_plural": "رویدادهای دسترسی اسناد", "ordering": ("-occurred_at", "-pk")},
        ),
        migrations.AddConstraint(
            model_name="documentrecord",
            constraint=models.CheckConstraint(condition=~models.Q(is_archived=True) | models.Q(archive_reason__gt=""), name="document_archive_requires_reason"),
        ),
        migrations.AddConstraint(
            model_name="documentrecord",
            constraint=models.CheckConstraint(condition=~models.Q(is_void=True) | models.Q(void_reason__gt=""), name="document_void_requires_reason"),
        ),
        migrations.AddConstraint(
            model_name="documentversion",
            constraint=models.UniqueConstraint(fields=("document", "version_number"), name="uniq_document_version"),
        ),
        migrations.AddConstraint(
            model_name="documentversion",
            constraint=models.UniqueConstraint(condition=models.Q(is_current=True), fields=("document",), name="uniq_document_current_version"),
        ),
        migrations.AddIndex(
            model_name="documentlink",
            index=models.Index(fields=["content_type", "object_id"], name="document_link_target"),
        ),
        migrations.AddConstraint(
            model_name="documentlink",
            constraint=models.UniqueConstraint(fields=("document", "content_type", "object_id"), name="uniq_document_link"),
        ),
        migrations.RunPython(backfill_initial_versions, migrations.RunPython.noop),
    ]
