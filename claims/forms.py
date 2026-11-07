from django import forms
from .models import ClaimObjection

class ClaimObjectionForm(forms.ModelForm):
    class Meta:
        model = ClaimObjection
        fields = ["description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class ClaimObjectionReviewForm(forms.Form):
    status = forms.ChoiceField(label="وضعیت اعتراض", choices=ClaimObjection.Status.choices)
    response = forms.CharField(
        label="پاسخ / توضیح رسیدگی",
        required=False,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == ClaimObjection.Status.ANSWERED and not (cleaned.get("response") or "").strip():
            self.add_error("response", "برای ثبت پاسخ اعتراض، درج توضیح الزامی است.")
        return cleaned
