from django.contrib import admin

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment
from auditlog.services import record_event
from .models import Insurer, Contract, ContractRevision


class GlobalReadOnlyAdmin(admin.ModelAdmin):
    readonly_fields = ()

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


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "contact_phone", "contact_email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "contact_email", "contact_phone")
    ordering = ("name",)

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
        # Insurer references may already be used by contracts, claims and payments.
        return False

    def save_model(self, request, obj, form, change):
        before = {}
        if change:
            previous = Insurer.objects.get(pk=obj.pk)
            before = {
                "name": previous.name, "contact_name": previous.contact_name,
                "contact_phone": previous.contact_phone,
                "contact_email": previous.contact_email, "is_active": previous.is_active,
            }
        super().save_model(request, obj, form, change)
        record_event(
            actor=request.user,
            action="insurer_updated" if change else "insurer_created",
            obj=obj, summary="ثبت یا تغییر اطلاعات مرجع بیمه‌گر",
            before_data=before,
            after_data={
                "name": obj.name, "contact_name": obj.contact_name,
                "contact_phone": obj.contact_phone,
                "contact_email": obj.contact_email, "is_active": obj.is_active,
            },
            request=request,
        )


@admin.register(Contract)
class ContractAdmin(GlobalReadOnlyAdmin):
    list_display = ("code", "title", "insurer", "line", "start_date", "end_date", "is_active")
    list_filter = ("line", "insurer", "is_active")
    search_fields = ("code", "title", "insurer__name")
    readonly_fields = tuple(field.name for field in Contract._meta.fields) + ("companies",)


@admin.register(ContractRevision)
class ContractRevisionAdmin(GlobalReadOnlyAdmin):
    list_display = ("contract", "revision_number", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("contract__code", "description")
    readonly_fields = tuple(field.name for field in ContractRevision._meta.fields)
