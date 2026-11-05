from django.contrib import admin

from .models import (
    BusinessCalendar, CalendarHoliday, WorkflowCase, WorkflowDefinition,
    WorkflowEvent, WorkflowStep, WorkflowTransition,
)


class WorkflowStepInline(admin.TabularInline):
    model = WorkflowStep
    extra = 0


class WorkflowTransitionInline(admin.TabularInline):
    model = WorkflowTransition
    fk_name = "definition"
    extra = 0


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "version", "is_active", "approved_by", "published_at")
    list_filter = ("is_active",)
    search_fields = ("code", "title")
    inlines = (WorkflowStepInline, WorkflowTransitionInline)


@admin.register(WorkflowCase)
class WorkflowCaseAdmin(admin.ModelAdmin):
    list_display = ("definition", "object_id", "current_step", "current_assignee", "status", "sla_due_at", "is_locked")
    list_filter = ("status", "is_locked", "definition")
    search_fields = ("object_id", "definition__code", "current_assignee__username")
    readonly_fields = tuple(field.name for field in WorkflowCase._meta.fields)

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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BusinessCalendar)
class BusinessCalendarAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "timezone_name", "start_time", "end_time", "is_active")


@admin.register(CalendarHoliday)
class CalendarHolidayAdmin(admin.ModelAdmin):
    list_display = ("calendar", "date", "title", "is_working_override")
    list_filter = ("calendar", "is_working_override")
    search_fields = ("title",)
