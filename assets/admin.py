from django.contrib import admin

from .models import AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle


class VehicleInline(admin.StackedInline):
    model = Vehicle
    extra = 0
    readonly_fields = tuple(field.name for field in Vehicle._meta.fields)
    can_delete = False
    max_num = 0


@admin.register(InsuredAsset)
class InsuredAssetAdmin(admin.ModelAdmin):
    list_display = ("asset_code", "name", "asset_type", "company", "person", "insurer", "policy_end", "is_active")
    list_filter = ("asset_type", "company", "insurer", "is_active")
    search_fields = ("asset_code", "name", "identifier", "policy_number", "company__name", "person__national_id")
    inlines = (VehicleInline,)
    readonly_fields = tuple(field.name for field in InsuredAsset._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "make", "model_name", "vin", "asset")
    search_fields = ("plate_number", "vin", "engine_number", "asset__asset_code")
    readonly_fields = tuple(field.name for field in Vehicle._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssetValuation)
class AssetValuationAdmin(admin.ModelAdmin):
    list_display = ("asset", "valuation_date", "market_value", "insured_value", "method", "created_by")
    list_filter = ("method", "valuation_date")
    search_fields = ("asset__asset_code", "asset__name", "source_reference")
    readonly_fields = tuple(field.name for field in AssetValuation._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssetPolicyPeriod)
class AssetPolicyPeriodAdmin(admin.ModelAdmin):
    list_display = ("asset", "policy_number", "insurer", "policy_start", "policy_end", "status")
    list_filter = ("insurer", "status")
    search_fields = ("asset__asset_code", "policy_number", "insurer__name")
    readonly_fields = tuple(field.name for field in AssetPolicyPeriod._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssetPolicyEndorsement)
class AssetPolicyEndorsementAdmin(admin.ModelAdmin):
    list_display = ("policy_period", "endorsement_number", "effective_date", "created_by")
    search_fields = ("policy_period__policy_number", "endorsement_number")
    readonly_fields = tuple(field.name for field in AssetPolicyEndorsement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
