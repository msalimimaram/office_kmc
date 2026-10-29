from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [("announcements", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="announcement",
            name="publish_at",
            field=models.DateTimeField(default=timezone.now, verbose_name="زمان انتشار"),
        ),
    ]
