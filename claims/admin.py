from django.contrib import admin

from .models import Claim, ClaimObjection, ClaimPayment


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ("claim_number", "source_claim_number", "person", "company_snapshot", "insurer", "status", "registered_date", "paid_amount")
    list_filter = ("status", "insurer", "company_snapshot")
    search_fields = ("claim_number", "source_claim_number", "person__national_id", "person__first_name", "person__last_name")
    readonly_fields = tuple(field.name for field in Claim._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClaimPayment)
class ClaimPaymentAdmin(admin.ModelAdmin):
    list_display = ("claim", "entry_type", "amount", "paid_at", "source_insurer", "recorded_by", "confirmed_by")
    list_filter = ("entry_type", "source_insurer", "paid_at")
    search_fields = ("claim__claim_number", "source_reference")
    readonly_fields = tuple(field.name for field in ClaimPayment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClaimObjection)
class ClaimObjectionAdmin(admin.ModelAdmin):
    list_display = ("claim", "submitted_by", "status", "deadline_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("claim__claim_number", "description", "response")
    readonly_fields = tuple(field.name for field in ClaimObjection._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
