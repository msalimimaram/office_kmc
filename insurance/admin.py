from django.contrib import admin

from .models import Insurer, Contract, ContractRevision


@admin.register(Insurer)
class InsurerAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "contact_phone", "contact_email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "contact_email", "contact_phone")
    ordering = ("name",)


admin.site.register(Contract)
admin.site.register(ContractRevision)
