from django import forms

from .models import WorkflowSatisfactionSurvey


class WorkflowSatisfactionForm(forms.ModelForm):
    class Meta:
        model = WorkflowSatisfactionSurvey
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.RadioSelect,
            "comment": forms.Textarea(attrs={"rows": 4, "maxlength": 1200}),
        }
