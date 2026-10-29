from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="user",
            name="date_joined",
            field=models.DateTimeField(default=timezone.now, verbose_name="date joined"),
        ),
    ]
