from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("اطلاعات اداره بیمه", {
        "fields": ("role", "mobile", "national_id", "company", "must_change_password", "mfa_enabled")
    }),)
    list_display = ("username", "first_name", "last_name", "role", "company", "is_active")
    list_filter = ("role", "company", "is_active")
