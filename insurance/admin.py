from django.contrib import admin

from .models import Contract, ContractRevision, Insurer


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "contact_phone", "contact_email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "contact_email", "contact_phone")
    ordering = ("name",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "insurer", "line", "start_date", "end_date", "is_active")
    list_filter = ("line", "insurer", "is_active")
    search_fields = ("code", "title", "insurer__name")
    autocomplete_fields = ("insurer", "companies")
    date_hierarchy = "start_date"
    list_select_related = ("insurer",)


@admin.register(ContractRevision)
class ContractRevisionAdmin(admin.ModelAdmin):
    list_display = ("contract", "revision_number", "created_by", "created_at")
    search_fields = ("contract__code", "contract__title", "description", "created_by__username")
    autocomplete_fields = ("contract", "created_by")
    readonly_fields = ("created_at",)
    list_select_related = ("contract", "created_by")
