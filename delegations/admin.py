from django.contrib import admin

from .models import DelegationEvent, WorkDelegation


class DelegationEventInline(admin.TabularInline):
    model = DelegationEvent
    extra = 0
    can_delete = False
    readonly_fields = ("actor", "event_type", "summary", "metadata", "created_at")


@admin.register(WorkDelegation)
class WorkDelegationAdmin(admin.ModelAdmin):
    list_display = (
        "workflow_code", "item_type", "delegate_role", "delegate_to",
        "granted_by", "status", "valid_from", "valid_until",
    )
    list_filter = ("status", "workflow_code", "delegate_role", "line_code")
    search_fields = ("workflow_code", "item_type", "delegate_to__username", "granted_by__username")
    readonly_fields = (
        "workflow_code", "item_type", "delegate_role", "delegate_to",
        "granted_by", "company", "insurer", "line_code", "reason",
        "valid_from", "valid_until", "revoked_at", "revoked_by",
        "revocation_reason", "created_at", "updated_at",
    )
    inlines = (DelegationEventInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DelegationEvent)
class DelegationEventAdmin(admin.ModelAdmin):
    list_display = ("delegation", "event_type", "actor", "created_at")
    readonly_fields = ("delegation", "actor", "event_type", "summary", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
