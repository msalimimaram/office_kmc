from django.contrib import admin

from .models import Company, Person


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "is_parent", "is_active")
    list_filter = ("is_parent", "is_active")
    search_fields = ("code", "name", "parent__name")
    ordering = ("name", "code")
    list_select_related = ("parent",)


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("national_id", "first_name", "last_name", "company", "relationship", "is_insured", "is_active")
    list_filter = ("relationship", "company", "is_insured", "is_active")
    search_fields = ("national_id", "personnel_code", "first_name", "last_name", "mobile")
    autocomplete_fields = ("company", "employee", "user")
    list_select_related = ("company", "employee", "user")
