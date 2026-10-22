from django import forms
from .models import Announcement
from core.uploads import validate_uploaded_file


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "audience", "company", "attachment", "is_published", "publish_at", "expires_at"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 7}),
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("publish_at") and cleaned.get("expires_at") and cleaned["expires_at"] <= cleaned["publish_at"]:
            self.add_error("expires_at", "پایان اعتبار باید بعد از زمان انتشار باشد.")
        attachment = cleaned.get("attachment")
        if attachment:
            error = validate_uploaded_file(attachment, max_size=15 * 1024 * 1024)
            if error:
                self.add_error("attachment", error)
        return cleaned
