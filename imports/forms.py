from django import forms

class ClaimImportForm(forms.Form):
    file = forms.FileField(label="فایل اکسل خسارت")
    def clean_file(self):
        f = self.cleaned_data["file"]
        import os
        if os.path.splitext(f.name)[1].lower() not in {".xlsx", ".xlsm"}:
            raise forms.ValidationError("فعلاً فقط فایل اکسل xlsx یا xlsm پشتیبانی می‌شود.")
        if f.size > 25 * 1024 * 1024:
            raise forms.ValidationError("حداکثر حجم فایل ۲۵ مگابایت است.")
        return f
