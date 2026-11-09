from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("claims", "0005_claim_duplicate_declaration_audit"),
    ]

    operations = [
        migrations.AlterField(
            model_name="claim",
            name="status",
            field=models.CharField(
                choices=[
                    ("registered", "ثبت‌شده"),
                    ("under_review", "در حال بررسی"),
                    ("needs_info", "نیازمند تکمیل اطلاعات"),
                    ("pending_decision", "در انتظار تصمیم نهایی"),
                    ("approved", "تأییدشده"),
                    ("rejected", "ردشده"),
                    ("partially_paid", "پرداخت بخشی"),
                    ("paid", "پرداخت‌شده"),
                    ("closed", "بسته‌شده"),
                ],
                default="registered",
                max_length=24,
                verbose_name="وضعیت",
            ),
        ),
    ]
