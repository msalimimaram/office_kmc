from django.contrib import admin

from .models import InternalTask, TaskEvent


class TaskEventInline(admin.TabularInline):
    model = TaskEvent
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in TaskEvent._meta.fields)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(InternalTask)
class InternalTaskAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "priority", "created_by", "due_at", "created_at")
    list_filter = ("status", "priority", "created_at")
    search_fields = ("title", "description", "created_by__username")
    readonly_fields = tuple(field.name for field in InternalTask._meta.fields)
    inlines = (TaskEventInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TaskEvent)
class TaskEventAdmin(admin.ModelAdmin):
    list_display = ("task", "event_type", "actor", "occurred_at")
    list_filter = ("event_type", "occurred_at")
    readonly_fields = tuple(field.name for field in TaskEvent._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
