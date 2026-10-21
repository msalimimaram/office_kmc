from django import forms
from .models import ServiceRequest

class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ["kind", "title", "description", "attachment"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}
    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        if f:
            if f.size > 10 * 1024 * 1024:
                raise forms.ValidationError("حداکثر حجم فایل ۱۰ مگابایت است.")
            allowed = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx"}
            import os
            if os.path.splitext(f.name)[1].lower() not in allowed:
                raise forms.ValidationError("نوع فایل مجاز نیست.")
        return f
