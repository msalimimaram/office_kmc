from django import forms
from .models import Person

class PersonChangeRequestForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["personnel_code", "national_id", "first_name", "last_name", "mobile", "iban", "is_insured"]
        widgets = {"national_id": forms.TextInput(attrs={"inputmode": "numeric"})}
