from django.contrib import admin

from .models import ImportBatch


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("batch_number", "source_type", "uploaded_by", "status", "total_rows", "valid_rows", "invalid_rows", "reviewed_by", "reviewed_at", "created_at")
    list_filter = ("status", "source_type", "created_at")
    search_fields = ("batch_number", "uploaded_by__username", "reviewed_by__username")
    readonly_fields = tuple(field.name for field in ImportBatch._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
