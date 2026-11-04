from django.contrib import admin

from .models import Correspondence, CorrespondenceEvent, CorrespondenceLink, CorrespondenceSequence


@admin.register(Correspondence)
class CorrespondenceAdmin(admin.ModelAdmin):
    list_display = ("internal_number", "subject", "channel", "direction", "company", "insurer", "follow_up_status", "follow_up_due", "assigned_to")
    list_filter = ("channel", "direction", "follow_up_status", "is_confidential", "company", "insurer")
    search_fields = ("internal_number", "subject", "summary", "external_reference", "company__name", "insurer__name")
    readonly_fields = tuple(field.name for field in Correspondence._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CorrespondenceSequence)
class CorrespondenceSequenceAdmin(admin.ModelAdmin):
    list_display = ("solar_date", "last_number", "updated_at")
    readonly_fields = tuple(field.name for field in CorrespondenceSequence._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CorrespondenceEvent)
class CorrespondenceEventAdmin(admin.ModelAdmin):
    list_display = ("correspondence", "event_type", "actor", "occurred_at")
    list_filter = ("event_type", "occurred_at")
    readonly_fields = tuple(field.name for field in CorrespondenceEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CorrespondenceLink)
class CorrespondenceLinkAdmin(admin.ModelAdmin):
    list_display = ("correspondence", "content_type", "object_id", "created_by", "created_at")
    readonly_fields = tuple(field.name for field in CorrespondenceLink._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
