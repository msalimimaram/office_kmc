from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "company", "is_published", "publish_at", "expires_at", "created_by")
    list_filter = ("audience", "company", "is_published")
    search_fields = ("title", "body", "company__name")
    readonly_fields = tuple(field.name for field in Announcement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
