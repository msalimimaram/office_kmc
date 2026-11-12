from django import forms
from organizations.models import Company, Person
from accounts.access import line_codes_for
from accounts.models import RoleAssignment
from .models import (
    AssetPolicyEndorsement, AssetPolicyPeriod, AssetValuation, InsuredAsset, Vehicle,
)


class InsuredAssetForm(forms.ModelForm):
    plate_number = forms.CharField(label="شماره پلاک", required=False, max_length=40)
    vin = forms.CharField(label="شماره شاسی/VIN", required=False, max_length=80)
    engine_number = forms.CharField(label="شماره موتور", required=False, max_length=80)
    make = forms.CharField(label="سازنده", required=False, max_length=100)
    model_name = forms.CharField(label="مدل خودرو", required=False, max_length=100)
    model_year = forms.IntegerField(label="سال ساخت", required=False, min_value=1900, max_value=2200)

    class Meta:
        model = InsuredAsset
        fields = [
            "asset_code", "name", "asset_type", "company", "person",
            "identifier", "location", "is_active", "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        company_qs = Company.objects.filter(is_active=True)
        person_qs = Person.objects.filter(is_active=True)
        if self.instance.pk:
            if self.instance.company_id:
                company_qs = (company_qs | Company.objects.filter(pk=self.instance.company_id)).distinct()
            if self.instance.person_id:
                person_qs = (person_qs | Person.objects.filter(pk=self.instance.person_id)).distinct()
        self.fields["company"].queryset = company_qs
        self.fields["person"].queryset = person_qs
        self.line_codes = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
        if self.instance.pk and self.instance.asset_type == InsuredAsset.Type.VEHICLE:
            try:
                vehicle = self.instance.vehicle_details
            except Vehicle.DoesNotExist:
                vehicle = None
            if vehicle:
                self.initial.update({
                    "plate_number": vehicle.plate_number,
                    "vin": vehicle.vin,
                    "engine_number": vehicle.engine_number,
                    "make": vehicle.make,
                    "model_name": vehicle.model_name,
                    "model_year": vehicle.model_year,
                })

    def clean(self):
        cleaned = super().clean()
        asset_type = cleaned.get("asset_type")
        if asset_type == InsuredAsset.Type.VEHICLE and not cleaned.get("plate_number"):
            self.add_error("plate_number", "برای خودرو، شماره پلاک الزامی است.")
        if (
            self.instance.pk
            and self.instance.asset_type == InsuredAsset.Type.VEHICLE
            and asset_type != InsuredAsset.Type.VEHICLE
        ):
            self.add_error("asset_type", "نوع دارایی خودروی دارای مشخصات را نمی‌توان به نوع دیگری تغییر داد.")
        company = cleaned.get("company")
        person = cleaned.get("person")
        if bool(company) == bool(person):
            self.add_error("company", "مالک دارایی را دقیقاً یک مورد از شرکت یا شخص انتخاب کنید.")
        if "*" not in self.line_codes:
            allowed = {
                InsuredAsset.Type.VEHICLE: {"third_party", "body", "vehicle"},
                InsuredAsset.Type.PROPERTY: {"fire", "property", "liability"},
                InsuredAsset.Type.EQUIPMENT: {"fire", "equipment", "liability"},
                InsuredAsset.Type.OTHER: {"other"},
            }
            permitted_lines = allowed.get(asset_type, set())
            if not self.line_codes or not self.line_codes.intersection(permitted_lines):
                self.add_error("asset_type", "انتصاب فعال شما اجازه ثبت این نوع دارایی را نمی‌دهد.")
        return cleaned


class AssetValuationForm(forms.ModelForm):
    class Meta:
        model = AssetValuation
        fields = [
            "valuation_date", "market_value", "insured_value", "method",
            "source_reference", "note",
        ]
        widgets = {
            "valuation_date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }


class AssetPolicyPeriodForm(forms.ModelForm):
    class Meta:
        model = AssetPolicyPeriod
        fields = [
            "insurer", "contract", "policy_number", "policy_start",
            "policy_end", "source_reference", "note",
        ]
        widgets = {
            "policy_start": forms.DateInput(attrs={"type": "date"}),
            "policy_end": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, asset, **kwargs):
        super().__init__(*args, **kwargs)
        self.asset = asset
        self.fields["insurer"].queryset = Insurer.objects.filter(is_active=True)
        contracts = Contract.objects.filter(is_active=True).select_related("insurer")
        company_id = asset.company_id or (asset.person.company_id if asset.person_id else None)
        if company_id:
            contracts = contracts.filter(companies__pk=company_id)
        self.fields["contract"].queryset = contracts.distinct()

    def clean(self):
        cleaned = super().clean()
        contract = cleaned.get("contract")
        insurer = cleaned.get("insurer")
        if contract and not insurer:
            cleaned["insurer"] = contract.insurer
        elif contract and insurer and contract.insurer_id != insurer.pk:
            self.add_error("insurer", "بیمه‌گر دوره باید با بیمه‌گر قرارداد یکسان باشد.")
        return cleaned


class AssetPolicyEndorsementForm(forms.ModelForm):
    class Meta:
        model = AssetPolicyEndorsement
        fields = ["policy_period", "endorsement_number", "effective_date", "description", "document"]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, asset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["policy_period"].queryset = asset.policy_periods.select_related("insurer", "contract")
