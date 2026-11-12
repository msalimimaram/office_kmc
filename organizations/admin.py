from django.contrib import admin
from django.core.exceptions import PermissionDenied

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from auditlog.services import record_event
from .models import Company, CompanyLeadershipPosition, Person, PersonChangeRequest


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_parent", "is_active")
    list_filter = ("is_parent", "is_active")
    search_fields = ("code", "name", "parent__name")
    ordering = ("name", "code")
    list_select_related = ("parent",)

    def _allowed(self, request):
        return bool(request.user and has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN))

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = {}
        if change:
            previous = Company.objects.get(pk=obj.pk)
            before = {
                "code": previous.code, "name": previous.name,
                "parent_id": previous.parent_id, "is_parent": previous.is_parent,
                "is_active": previous.is_active,
            }
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="company_updated" if change else "company_created",
            obj=obj, summary="ثبت یا تغییر اطلاعات پایه شرکت",
            before_data=before,
            after_data={
                "code": obj.code, "name": obj.name,
                "parent_id": obj.parent_id, "is_parent": obj.is_parent,
                "is_active": obj.is_active,
            },
            request=request,
        )


@admin.register(CompanyLeadershipPosition)
class CompanyLeadershipPositionAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "code", "is_active", "updated_at")
    list_filter = ("company", "is_active")
    search_fields = ("title", "code", "company__name")
    ordering = ("company__name", "title")

    def has_module_permission(self, request):
        return has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)

    def has_view_permission(self, request, obj=None):
        return has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)

    def has_add_permission(self, request):
        return has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)

    def has_change_permission(self, request, obj=None):
        return has_role(request.user, RoleAssignment.Role.SYSTEM_ADMIN)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = {}
        if change:
            previous = CompanyLeadershipPosition.objects.get(pk=obj.pk)
            before = {"company_id": previous.company_id, "code": previous.code, "title": previous.title, "is_active": previous.is_active}
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="company_leadership_position_updated" if change else "company_leadership_position_created",
            obj=obj, summary="ثبت یا تغییر فهرست سمت‌های مدیریتی شرکت",
            before_data=before,
            after_data={"company_id": obj.company_id, "code": obj.code, "title": obj.title, "is_active": obj.is_active},
            request=request,
        )


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("national_id", "personnel_code", "first_name", "last_name", "company", "is_insured", "is_active")
    list_filter = ("company", "is_insured", "is_active", "relationship")
    search_fields = ("national_id", "personnel_code", "first_name", "last_name", "company__name")
    ordering = ("last_name", "first_name", "pk")

    def has_module_permission(self, request):
        return bool(request.user and has_global_access(request.user))

    def has_view_permission(self, request, obj=None):
        return bool(request.user and has_global_access(request.user))

    def has_add_permission(self, request):
        # Initial/manual person creation remains available to authorised global operators.
        return bool(request.user and has_global_access(request.user))

    def has_change_permission(self, request, obj=None):
        # Identity, contact and banking changes must use the approved change workflow.
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            raise PermissionDenied("اطلاعات هویتی فقط از مسیر گردش اصلاح اطلاعات تغییر می‌کند.")
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="insured_person_created",
            obj=obj,
            summary="ایجاد پرونده پایه بیمه‌شده",
            after_data={
                "company_id": obj.company_id,
                "national_id_masked": f"***{(obj.national_id or '')[-3:]}",
                "personnel_code": obj.personnel_code,
                "relationship": obj.relationship,
                "is_insured": obj.is_insured,
                "is_active": obj.is_active,
            },
            request=request,
        )


@admin.register(PersonChangeRequest)
class PersonChangeRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id", "person", "company", "change_type", "status",
        "requested_by", "created_at", "approved_by",
    )
    list_filter = ("change_type", "status", "company")
    search_fields = (
        "person__national_id", "person__personnel_code",
        "person__first_name", "person__last_name",
        "contract__code", "requested_by__username",
    )
    readonly_fields = tuple(field.name for field in PersonChangeRequest._meta.fields)

    def has_module_permission(self, request):
        return bool(request.user and has_global_access(request.user))

    def has_view_permission(self, request, obj=None):
        return bool(request.user and has_global_access(request.user))

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
