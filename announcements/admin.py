from django.contrib import admin
from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "company", "is_published", "publish_at", "expires_at", "created_by")
    list_filter = ("audience", "company", "is_published")
    search_fields = ("title", "body", "company__name")
    readonly_fields = ("created_at", "updated_at")
