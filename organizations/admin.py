from django.contrib import admin

from accounts.access import has_global_access
from .models import Company, Person, PersonChangeRequest


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_parent", "is_active")
    list_filter = ("is_parent", "is_active")
    search_fields = ("code", "name", "parent__name")
    ordering = ("name", "code")
    list_select_related = ("parent",)


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
