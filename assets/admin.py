from django.contrib import admin
from .models import InsuredAsset, Vehicle


class VehicleInline(admin.StackedInline):
    model = Vehicle
    extra = 0


@admin.register(InsuredAsset)
class InsuredAssetAdmin(admin.ModelAdmin):
    list_display = ("asset_code", "name", "asset_type", "company", "insurer", "policy_end", "is_active")
    list_filter = ("asset_type", "company", "insurer", "is_active")
    search_fields = ("asset_code", "name", "identifier", "policy_number", "company__name")
    inlines = (VehicleInline,)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("plate_number", "make", "model_name", "vin", "asset")
    search_fields = ("plate_number", "vin", "engine_number", "asset__asset_code")
