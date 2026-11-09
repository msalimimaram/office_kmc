from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("claims", "0003_alter_claimpayment_options_alter_claim_claim_number_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="claim",
            name="assessed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assessed_claims",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="claim",
            name="assessed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="زمان ارزیابی"),
        ),
    ]
