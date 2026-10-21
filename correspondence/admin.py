from django.contrib import admin
from .models import Correspondence


@admin.register(Correspondence)
class CorrespondenceAdmin(admin.ModelAdmin):
    list_display = ("subject", "channel", "direction", "company", "insurer", "follow_up_status", "follow_up_due", "assigned_to")
    list_filter = ("channel", "direction", "follow_up_status", "is_confidential", "company", "insurer")
    search_fields = ("subject", "summary", "external_reference", "company__name", "insurer__name")
    readonly_fields = ("created_at", "updated_at")
