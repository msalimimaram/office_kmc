from django import forms
from .models import ClaimObjection

class ClaimObjectionForm(forms.ModelForm):
    class Meta:
        model = ClaimObjection
        fields = ["description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
