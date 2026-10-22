from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from organizations.models import Person
from .models import ServiceRequest


class ServiceRequestForm(forms.ModelForm):
    person = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        required=False,
        label="بیمه‌شده مرتبط",
        help_text="برای درخواست کمک‌هزینه درمان، خود بیمه‌شده یا فرد تحت تکفل را انتخاب کنید.",
    )

    class Meta:
        model = ServiceRequest
        fields = ["kind", "person", "title", "description", "attachment"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user and user.role == "employee":
            if user.company_id and user.national_id:
                self.fields["person"].queryset = Person.objects.filter(
                    company_id=user.company_id,
                    is_active=True,
                    is_insured=True,
                ).filter(
                    Q(national_id=user.national_id) |
                    Q(employee__national_id=user.national_id)
                ).distinct().order_by("relationship", "last_name", "first_name")
            else:
                self.fields["person"].queryset = Person.objects.none()
        else:
            # Other roles do not get an unrestricted person selector from this form.
            self.fields.pop("person")

    def clean(self):
        cleaned = super().clean()
        if (
            self.user
            and self.user.role == "employee"
            and cleaned.get("kind") == ServiceRequest.Kind.MEDICAL_ASSISTANCE
            and not cleaned.get("person")
        ):
            self.add_error("person", "برای درخواست کمک‌هزینه درمان، انتخاب بیمه‌شده یا فرد تحت تکفل الزامی است.")
        return cleaned

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
