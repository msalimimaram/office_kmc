from django import forms
from .models import InternalTask

class InternalTaskForm(forms.ModelForm):
    class Meta:
        model = InternalTask
        fields = ["title", "description", "assignees", "priority", "due_at", "related_request"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4}), "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}
