from django.contrib import admin

from .models import Company, Person


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_parent", "is_active")
    list_filter = ("is_parent", "is_active")
    search_fields = ("code", "name", "parent__name")
    ordering = ("name", "code")
    list_select_related = ("parent",)


admin.site.register(Person)
