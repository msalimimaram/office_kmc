# Generated for immutable optional workflow satisfaction feedback.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0007_alter_workflowstep_allowed_roles_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowSatisfactionSurvey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.PositiveSmallIntegerField(verbose_name="امتیاز رضایت")),
                ("comment", models.TextField(blank=True, max_length=1200, verbose_name="نظر تکمیلی")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("respondent", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="workflow_satisfaction_surveys", to=settings.AUTH_USER_MODEL)),
                ("workflow_case", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="satisfaction_surveys", to="workflow.workflowcase")),
            ],
            options={
                "verbose_name": "ارزیابی رضایت از رسیدگی",
                "verbose_name_plural": "ارزیابی‌های رضایت از رسیدگی",
                "ordering": ("-created_at", "-pk"),
            },
        ),
        migrations.AddConstraint(
            model_name="workflowsatisfactionsurvey",
            constraint=models.UniqueConstraint(fields=("workflow_case", "respondent"), name="uniq_workflow_survey_respondent"),
        ),
        migrations.AddConstraint(
            model_name="workflowsatisfactionsurvey",
            constraint=models.CheckConstraint(condition=models.Q(("rating__gte", 1), ("rating__lte", 5)), name="workflow_survey_rating_1_5"),
        ),
    ]
