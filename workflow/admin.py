from django.contrib import admin

from accounts.models import RoleAssignment
from accounts.access import has_global_access
from .governance import has_active_governance_assignment
from auditlog.services import record_event
from .models import (
    BusinessCalendar, CalendarHoliday, WorkflowCase, WorkflowDefinition,
    WorkflowEvent, WorkflowStep, WorkflowTransition,
)


def can_configure(request):
    # Workflow configuration is a proposal-writing privilege, not an approval privilege.
    return has_active_governance_assignment(request.user, RoleAssignment.Role.SYSTEM_ADMIN)


def can_view_operations(request):
    # Both global business roles retain read-only operational oversight.
    return has_global_access(request.user)


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0

    def has_add_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))

    def has_change_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))

    def has_delete_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))


class WorkflowTransitionInline(admin.TabularInline):
    model = WorkflowTransition
    fk_name = "definition"
    extra = 0

    def has_add_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))

    def has_change_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))

    def has_delete_permission(self, request, obj=None):
        return can_configure(request) and not (obj and (obj.is_active or obj.published_at))


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "version", "is_active", "approved_by", "published_at")
    list_filter = ("is_active",)
    search_fields = ("code", "title")
    inlines = (WorkflowStepInline, WorkflowTransitionInline)
    readonly_fields = ("created_by", "approved_by", "is_active", "published_at")

    def has_module_permission(self, request):
        return can_configure(request)

    def has_view_permission(self, request, obj=None):
        return can_configure(request)

    def has_add_permission(self, request):
        return can_configure(request)

    def has_change_permission(self, request, obj=None):
        return can_configure(request) and (
            obj is None or (not obj.is_active and obj.published_at is None)
        )

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            previous = type(obj).objects.get(pk=obj.pk)
            before = {
                "code": previous.code,
                "version": previous.version,
                "title": previous.title,
                "description": previous.description,
            }
        else:
            obj.created_by = request.user

        # Admin can only save a draft proposal. Approval fields are assigned
        # exclusively by the authenticated Department Head governance action.
        obj.approved_by = None
        obj.is_active = False
        obj.published_at = None
        super().save_model(request, obj, form, change)
        after = {
            "code": obj.code,
            "version": obj.version,
            "title": obj.title,
            "description": obj.description,
            "status": "draft",
        }
        record_event(
            actor=request.user,
            action="workflow.definition.proposed" if not change else "workflow.definition.proposal_updated",
            obj=obj,
            summary="پیشنهاد نسخه گردش‌کار توسط مدیر سامانه ثبت/به‌روزرسانی شد.",
            before_data=before or {},
            after_data=after,
            request=request,
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkflowCase)
class WorkflowCaseAdmin(admin.ModelAdmin):
    list_display = ("definition", "object_id", "current_step", "current_assignee", "status", "sla_due_at", "is_locked")
    list_filter = ("status", "is_locked", "definition")
    search_fields = ("object_id", "definition__code", "current_assignee__username")
    readonly_fields = tuple(field.name for field in WorkflowCase._meta.fields)

    def has_module_permission(self, request):
        return can_view_operations(request)

    def has_view_permission(self, request, obj=None):
        return can_view_operations(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkflowEvent)
class WorkflowEventAdmin(admin.ModelAdmin):
    list_display = ("workflow_case", "event_type", "actor", "sent_at")
    list_filter = ("event_type", "sent_at")
    readonly_fields = tuple(field.name for field in WorkflowEvent._meta.fields)

    def has_module_permission(self, request):
        return can_view_operations(request)

    def has_view_permission(self, request, obj=None):
        return can_view_operations(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BusinessCalendar)
class BusinessCalendarAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "timezone_name", "start_time", "end_time", "is_active")

    def has_module_permission(self, request):
        return can_configure(request)

    def has_view_permission(self, request, obj=None):
        return can_configure(request)

    def has_add_permission(self, request):
        return can_configure(request)

    def has_change_permission(self, request, obj=None):
        return can_configure(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CalendarHoliday)
class CalendarHolidayAdmin(admin.ModelAdmin):
    list_display = ("calendar", "date", "title", "is_working_override")
    list_filter = ("calendar", "is_working_override")
    search_fields = ("title",)

    def has_module_permission(self, request):
        return can_configure(request)

    def has_view_permission(self, request, obj=None):
        return can_configure(request)

    def has_add_permission(self, request):
        return can_configure(request)

    def has_change_permission(self, request, obj=None):
        return can_configure(request)

    def has_delete_permission(self, request, obj=None):
        return False
