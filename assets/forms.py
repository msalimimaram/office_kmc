from django import forms
from insurance.models import Contract, Insurer
from organizations.models import Company
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
            "asset_code", "name", "asset_type", "company", "identifier", "location",
            "insured_value", "insurer", "contract", "policy_number", "policy_start",
            "policy_end", "is_active", "notes",
        ]
        widgets = {
            "policy_start": forms.DateInput(attrs={"type": "date"}),
            "policy_end": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user.role == "subsidiary_rep" and user.company_id:
            self.fields.pop("company")
            self.fields["contract"].queryset = Contract.objects.filter(companies=user.company, is_active=True)
            self.fields["insurer"].queryset = Insurer.objects.filter(contracts__companies=user.company, is_active=True).distinct()
        if "company" in self.fields:
            self.fields["company"].queryset = Company.objects.filter(is_active=True)
        if "contract" in self.fields:
            self.fields["contract"].queryset = self.fields["contract"].queryset.select_related("insurer")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("asset_type") == InsuredAsset.Type.VEHICLE and not cleaned.get("plate_number"):
            self.add_error("plate_number", "برای دارایی از نوع خودرو، شماره پلاک الزامی است.")
        if cleaned.get("policy_start") and cleaned.get("policy_end") and cleaned["policy_end"] < cleaned["policy_start"]:
            self.add_error("policy_end", "پایان پوشش نمی‌تواند قبل از شروع پوشش باشد.")
        contract = cleaned.get("contract")
        insurer = cleaned.get("insurer")
        if contract and insurer and contract.insurer_id != insurer.pk:
            self.add_error("insurer", "بیمه‌گر انتخاب‌شده با بیمه‌گر قرارداد یکسان نیست.")
        if contract and self.user.role == "subsidiary_rep" and not contract.companies.filter(pk=self.user.company_id).exists():
            self.add_error("contract", "این قرارداد برای شرکت شما تعریف نشده است.")
        return cleaned
