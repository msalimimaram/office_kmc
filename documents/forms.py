from django import forms


class DocumentVersionForm(forms.Form):
    file = forms.FileField(label="فایل نسخه جدید")
    change_reason = forms.CharField(
        label="شرح تغییر",
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class DocumentLifecycleActionForm(forms.Form):
    reason = forms.CharField(
        label="دلیل اقدام",
        min_length=3,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
