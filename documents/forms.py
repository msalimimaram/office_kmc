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



class DocumentLinkForm(forms.Form):
    TARGET_CHOICES = (
        ("claim", "خسارت"),
        ("request", "درخواست"),
        ("correspondence", "مکاتبه"),
        ("contract", "قرارداد"),
        ("asset", "دارایی"),
        ("task", "وظیفه"),
    )
    target_type = forms.ChoiceField(label="نوع رکورد مرتبط", choices=TARGET_CHOICES)
    target_id = forms.IntegerField(label="شناسه رکورد", min_value=1)
