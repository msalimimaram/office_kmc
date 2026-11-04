from django import forms
from insurance.models import Contract, Insurer
from organizations.models import Company, Person
from accounts.access import line_codes_for
from accounts.models import RoleAssignment
from .models import InsuredAsset


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
            "asset_code", "name", "asset_type", "company", "person", "identifier",
            "location", "insured_value", "insurer", "contract", "policy_number",
            "policy_start", "policy_end", "is_active", "notes",
        ]
        widgets = {
            "policy_start": forms.DateInput(attrs={"type": "date"}),
            "policy_end": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["company"].queryset = Company.objects.filter(is_active=True)
        self.fields["person"].queryset = Person.objects.filter(is_active=True)
        self.fields["contract"].queryset = Contract.objects.filter(is_active=True).select_related("insurer")
        self.fields["insurer"].queryset = Insurer.objects.filter(is_active=True)
        self.line_codes = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)

    def clean(self):
        cleaned = super().clean()
        asset_type = cleaned.get("asset_type")
        if asset_type == InsuredAsset.Type.VEHICLE and not cleaned.get("plate_number"):
            self.add_error("plate_number", "برای خودرو، شماره پلاک الزامی است.")
        if cleaned.get("policy_start") and cleaned.get("policy_end") and cleaned["policy_end"] < cleaned["policy_start"]:
            self.add_error("policy_end", "پایان پوشش نمی‌تواند قبل از شروع پوشش باشد.")

        company = cleaned.get("company")
        person = cleaned.get("person")
        if bool(company) == bool(person):
            self.add_error("company", "مالک دارایی را دقیقاً یک مورد از شرکت یا شخص انتخاب کنید.")

        contract = cleaned.get("contract")
        insurer = cleaned.get("insurer")
        if contract and not insurer:
            cleaned["insurer"] = contract.insurer
        elif contract and insurer and contract.insurer_id != insurer.pk:
            self.add_error("insurer", "بیمه‌گر انتخاب‌شده با بیمه‌گر قرارداد یکسان نیست.")
        if contract and company and not contract.companies.filter(pk=company.pk).exists():
            self.add_error("contract", "این قرارداد برای شرکت انتخاب‌شده تعریف نشده است.")
        if contract and person and person.company_id and not contract.companies.filter(pk=person.company_id).exists():
            self.add_error("contract", "این قرارداد برای شرکت محل اشتغال شخص تعریف نشده است.")

        if asset_type == InsuredAsset.Type.VEHICLE and self.line_codes and not (
            "*" in self.line_codes or self.line_codes.intersection({"third_party", "body", "vehicle"})
        ):
            self.add_error("asset_type", "انتصاب شما اجازه ثبت دارایی خودرو را نمی‌دهد.")
        return cleaned
