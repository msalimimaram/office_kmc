from django.contrib import admin

from accounts.access import has_global_access
from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "object_type", "object_id", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "actor__first_name", "actor__last_name", "object_type", "object_id", "summary")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # is_staff is a technical Django flag, not a current business grant.
        return bool(
            request.user
            and request.user.is_authenticated
            and has_global_access(request.user)
        )
