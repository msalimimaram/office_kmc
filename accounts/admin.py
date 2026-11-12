from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from auditlog.services import record_event
from .access import has_role
from .models import (
    OrganizationalPosition,
    OrganizationalUnit,
    PositionAssignment,
    RoleAssignment,
    User,
    UserNotification,
)


def _user_snapshot(obj):
    return {
        "username": obj.username,
        "first_name": obj.first_name,
        "last_name": obj.last_name,
        "email": obj.email,
        "is_active": obj.is_active,
        "must_change_password": obj.must_change_password,
        "legacy_role": obj.role,
        "legacy_company_id": obj.company_id,
        "legacy_insurer_id": obj.insurer_id,
        "national_id_masked": f"***{(obj.national_id or '')[-3:]}" if obj.national_id else "",
    }


def _role_assignment_snapshot(obj):
    return {
        "user_id": obj.user_id,
        "role": obj.role,
        "company_id": obj.company_id,
        "insurer_id": obj.insurer_id,
        "organizational_unit_id": obj.organizational_unit_id,
        "position_id": obj.position_id,
        "line_code": obj.line_code,
        "valid_from": obj.valid_from.isoformat() if obj.valid_from else None,
        "valid_until": obj.valid_until.isoformat() if obj.valid_until else None,
        "is_active": obj.is_active,
        "reason": obj.reason,
        "approved_by_id": obj.approved_by_id,
        "granted_by_id": obj.granted_by_id,
    }


def _position_assignment_snapshot(obj):
    return {
        "user_id": obj.user_id,
        "unit_id": obj.unit_id,
        "position_id": obj.position_id,
        "line_code": obj.line_code,
        "valid_from": obj.valid_from.isoformat() if obj.valid_from else None,
        "valid_until": obj.valid_until.isoformat() if obj.valid_until else None,
        "is_active": obj.is_active,
        "reason": obj.reason,
        "approved_by_id": obj.approved_by_id,
        "granted_by_id": obj.granted_by_id,
    }


def _unit_snapshot(obj):
    return {
        "code": obj.code, "name": obj.name, "parent_id": obj.parent_id,
        "company_id": obj.company_id, "is_active": obj.is_active,
    }


def _position_snapshot(obj):
    return {
        "title": obj.title, "code": obj.code, "unit_id": obj.unit_id,
        "level": obj.level, "is_active": obj.is_active,
    }


def is_system_admin(request):
    return bool(
        request.user
        and request.user.is_authenticated
        and has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)
    )


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # Business access is granted only by RoleAssignment. Do not expose Django's
    # is_staff/is_superuser/groups/permissions switches in this business UI.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("اطلاعات شخصی", {"fields": ("first_name", "last_name", "email", "mobile", "national_id")}),
        ("وضعیت حساب", {"fields": ("is_active", "must_change_password", "mfa_enabled")}),
        ("اطلاعات سازگاری قدیمی (فقط مشاهده)", {"fields": ("role", "company", "insurer")}),
        ("تاریخ‌ها", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {
        "classes": ("wide",),
        "fields": ("username", "password1", "password2"),
    }),)
    list_display = ("username", "first_name", "last_name", "role", "company", "insurer", "is_active")
    list_filter = ("role", "company", "insurer", "is_active")
    readonly_fields = (
        "date_joined", "last_login", "role", "mobile", "national_id",
        "company", "insurer", "mfa_enabled",
    )

    def save_model(self, request, obj, form, change):
        before = _user_snapshot(User.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="user_account_updated" if change else "user_account_created",
            obj=obj,
            summary="ثبت تغییرات حساب کاربری توسط مدیر سامانه",
            before_data=before,
            after_data=_user_snapshot(obj),
            request=request,
        )

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
        before = _role_assignment_snapshot(RoleAssignment.objects.get(pk=obj.pk)) if change else {}
        if not change and not obj.granted_by_id:
            obj.granted_by = request.user
        if not obj.approved_by_id:
            obj.approved_by = request.user
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="role_assignment_updated" if change else "role_assignment_created",
            obj=obj,
            summary="ثبت انتصاب یا تغییر دامنه نقش عملیاتی",
            before_data=before,
            after_data=_role_assignment_snapshot(obj),
            request=request,
        )


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

    def save_model(self, request, obj, form, change):
        before = _unit_snapshot(OrganizationalUnit.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="organizational_unit_updated" if change else "organizational_unit_created",
            obj=obj, summary="ثبت تغییر در ساختار واحدهای سازمانی",
            before_data=before, after_data=_unit_snapshot(obj), request=request,
        )


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

    def save_model(self, request, obj, form, change):
        before = _position_snapshot(OrganizationalPosition.objects.get(pk=obj.pk)) if change else {}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="organizational_position_updated" if change else "organizational_position_created",
            obj=obj, summary="ثبت تغییر در فهرست سمت‌های سازمانی",
            before_data=before, after_data=_position_snapshot(obj), request=request,
        )


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

    def save_model(self, request, obj, form, change):
        before = _position_assignment_snapshot(PositionAssignment.objects.get(pk=obj.pk)) if change else {}
        if not change and not obj.granted_by_id:
            obj.granted_by = request.user
        if not obj.approved_by_id:
            obj.approved_by = request.user
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="position_assignment_updated" if change else "position_assignment_created",
            obj=obj, summary="ثبت انتصاب یا تغییر سمت سازمانی",
            before_data=before, after_data=_position_assignment_snapshot(obj), request=request,
        )


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "actor", "created_at", "read_at")
    list_filter = ("created_at", "read_at")
    search_fields = ("recipient__username", "title", "body")
    readonly_fields = tuple(field.name for field in UserNotification._meta.fields)

    def has_module_permission(self, request):
        return is_system_admin(request)

    def has_view_permission(self, request, obj=None):
        return is_system_admin(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
