from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("claims", "0002_claim_history_and_payments"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="claimpayment",
            options={
                "ordering": ("claim_id", "paid_at", "created_at", "pk"),
                "verbose_name": "رویداد پرداخت خسارت",
                "verbose_name_plural": "رویدادهای پرداخت خسارت",
            },
        ),
        migrations.AlterField(
            model_name="claim",
            name="claim_number",
            field=models.CharField(max_length=100, unique=True, verbose_name="شناسه داخلی خسارت"),
        ),
        migrations.AlterField(
            model_name="claim",
            name="paid_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=16,
                verbose_name="مبلغ پرداخت‌شده طبق اعلام منبع (مقدار تجمیعی سازگاری)",
            ),
        ),
        migrations.AlterField(
            model_name="claim",
            name="payment_date",
            field=models.DateField(blank=True, null=True, verbose_name="آخرین تاریخ پرداخت قدیمی"),
        ),
        migrations.AlterField(
            model_name="claim",
            name="service_date",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ خسارت/خدمت"),
        ),
        migrations.AlterField(
            model_name="claim",
            name="service_type",
            field=models.CharField(
                help_text="نوع خدمت و اطلاعات غیرپزشکی؛ دسترسی به اسناد پزشکی تابع سطح محرمانگی است.",
                max_length=120,
                verbose_name="نوع خدمت",
            ),
        ),
        migrations.AlterField(
            model_name="claimpayment",
            name="amount",
            field=models.DecimalField(decimal_places=2, max_digits=16, verbose_name="مبلغ"),
        ),
        migrations.AlterField(
            model_name="claimpayment",
            name="paid_at",
            field=models.DateField(blank=True, null=True, verbose_name="تاریخ پرداخت/اصلاح"),
        ),
    ]
