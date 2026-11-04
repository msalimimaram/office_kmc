from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .access import has_role
from .models import (
    OrganizationalPosition,
    OrganizationalUnit,
    PositionAssignment,
    RoleAssignment,
    User,
)


def is_system_admin(request):
    return bool(
        request.user
        and request.user.is_authenticated
        and (request.user.is_superuser or has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN))
    )


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("اطلاعات سازگاری قدیمی", {
        "fields": ("role", "mobile", "national_id", "company", "insurer", "must_change_password", "mfa_enabled")
    }),)
    list_display = ("username", "first_name", "last_name", "role", "company", "insurer", "is_active")
    list_filter = ("role", "company", "insurer", "is_active")
    readonly_fields = ("date_joined", "last_login")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "company", "insurer", "line_code", "valid_from", "valid_until", "is_active")
    list_filter = ("role", "company", "insurer", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "reason")
    readonly_fields = ("created_at", "updated_at", "granted_by")
    autocomplete_fields = ("user", "company", "insurer", "organizational_unit", "position", "approved_by")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change and not obj.granted_by_id:
            obj.granted_by = request.user
        if not obj.approved_by_id:
            obj.approved_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(OrganizationalUnit)
class OrganizationalUnitAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "company", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("code", "name")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrganizationalPosition)
class OrganizationalPositionAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "unit", "level", "is_active")
    list_filter = ("unit", "level", "is_active")
    search_fields = ("title", "code", "unit__name")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PositionAssignment)
class PositionAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "unit", "position", "line_code", "valid_from", "valid_until", "is_active")
    list_filter = ("unit", "position", "is_active")
    search_fields = ("user__username", "user__first_name", "user__last_name", "position__title")
    readonly_fields = ("created_at", "granted_by")
    autocomplete_fields = ("user", "unit", "position", "approved_by")

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return is_system_admin(request)

    def has_change_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_delete_permission(self, request, obj=None):
        return False
