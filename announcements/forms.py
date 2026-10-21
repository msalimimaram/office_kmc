from django import forms
from .models import Announcement


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
            if attachment.size > 15 * 1024 * 1024:
                self.add_error("attachment", "حداکثر حجم پیوست ۱۵ مگابایت است.")
            elif attachment.name.rsplit(".", 1)[-1].lower() not in {"pdf", "docx", "xlsx", "png", "jpg", "jpeg"}:
                self.add_error("attachment", "نوع پیوست مجاز نیست.")
        return cleaned
