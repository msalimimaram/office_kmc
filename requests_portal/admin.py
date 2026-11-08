from django.contrib import admin

from accounts.access import has_global_access
from .models import ServiceRequest


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = (
        "reference", "kind", "title", "company", "status",
        "assigned_to", "submitted_by", "created_at",
    )
    list_filter = ("kind", "status", "is_confidential", "created_at")
    search_fields = (
        "reference", "title", "submitted_by__username",
        "company__name", "person__national_id",
    )
    ordering = ("-created_at", "-pk")
    readonly_fields = tuple(field.name for field in ServiceRequest._meta.fields)

    def has_module_permission(self, request):
        return bool(request.user and has_global_access(request.user))

    def has_view_permission(self, request, obj=None):
        return bool(request.user and has_global_access(request.user))

    def has_add_permission(self, request):
        # Requests must enter through the scoped portal and start their workflow there.
        return False

    def has_change_permission(self, request, obj=None):
        # Direct Admin edits bypass workflow transitions and domain audit events.
        return False

    def has_delete_permission(self, request, obj=None):
        return False
