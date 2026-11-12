from django import forms

from .models import WorkflowSatisfactionSurvey


class WorkflowSatisfactionForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        label="میزان رضایت",
        choices=[(1, "۱ — بسیار ضعیف"), (2, "۲ — ضعیف"), (3, "۳ — متوسط"), (4, "۴ — خوب"), (5, "۵ — بسیار خوب")],
        coerce=int,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = WorkflowSatisfactionSurvey
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.RadioSelect,
            "comment": forms.Textarea(attrs={"rows": 4, "maxlength": 1200}),
        }
