from django.contrib import admin

from .models import DocumentAccessEvent, DocumentRecord, DocumentVersion


@admin.register(DocumentRecord)
class DocumentRecordAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "company", "person", "security_level", "is_medical", "is_archived", "is_void", "created_at")
    list_filter = ("security_level", "is_medical", "is_archived", "is_void", "company")
    search_fields = ("title", "category", "person__national_id", "company__name")
    readonly_fields = tuple(field.name for field in DocumentRecord._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "uploaded_by", "is_current", "uploaded_at", "checksum_sha256")
    list_filter = ("is_current", "uploaded_at")
    search_fields = ("document__title", "uploaded_by__username", "checksum_sha256")
    readonly_fields = tuple(field.name for field in DocumentVersion._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DocumentAccessEvent)
class DocumentAccessEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "actor", "document", "version", "action", "ip_address")
    list_filter = ("action", "occurred_at")
    search_fields = ("actor__username", "document__title")
    readonly_fields = tuple(field.name for field in DocumentAccessEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
