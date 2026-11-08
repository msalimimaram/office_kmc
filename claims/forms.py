from decimal import Decimal

from django import forms

from accounts.access import has_global_access, has_role
from accounts.models import RoleAssignment, User
from insurance.models import Insurer
from .models import ClaimObjection

class ClaimObjectionForm(forms.ModelForm):
    class Meta:
        model = ClaimObjection
        fields = ["description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}


class ClaimObjectionReviewForm(forms.Form):
    status = forms.ChoiceField(label="وضعیت اعتراض", choices=ClaimObjection.Status.choices)
    response = forms.CharField(
        label="پاسخ / توضیح رسیدگی",
        required=False,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == ClaimObjection.Status.ANSWERED and not (cleaned.get("response") or "").strip():
            self.add_error("response", "برای ثبت پاسخ اعتراض، درج توضیح الزامی است.")
        return cleaned



class _IndependentClaimPaymentReviewerFormMixin:
    def _set_reviewers(self, *, claim, user):
        line_code = claim.contract.line if claim.contract_id else "health"
        eligible_ids = []
        for candidate in User.objects.filter(is_active=True).exclude(pk=user.pk).iterator():
            if has_global_access(candidate) or has_role(
                candidate, RoleAssignment.Role.INSURANCE_SPECIALIST, line_code=line_code
            ):
                eligible_ids.append(candidate.pk)
        self.fields["confirmed_by"].queryset = User.objects.filter(
            pk__in=eligible_ids, is_active=True
        ).order_by("username")


class ClaimPaymentForm(_IndependentClaimPaymentReviewerFormMixin, forms.Form):
    amount = forms.DecimalField(
        label="مبلغ پرداخت",
        max_digits=16,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    paid_at = forms.DateField(
        label="تاریخ پرداخت",
        required=False,
        input_formats=["%Y-%m-%d", "%Y/%m/%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    source_reference = forms.CharField(label="شماره حواله/مرجع منبع", required=False, max_length=160)
    source_insurer = forms.ModelChoiceField(
        label="بیمه‌گر اعلام‌کننده",
        queryset=Insurer.objects.none(),
        required=False,
    )
    confirmed_by = forms.ModelChoiceField(
        label="تأییدکننده مستقل",
        queryset=User.objects.none(),
        empty_label="انتخاب تأییدکننده",
    )
    note = forms.CharField(label="توضیحات", required=False, max_length=5000, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, claim=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if claim and user:
            self._set_reviewers(claim=claim, user=user)
            self.fields["source_insurer"].queryset = (
                Insurer.objects.filter(pk=claim.insurer_id)
                if claim.insurer_id else Insurer.objects.none()
            )


class ClaimPaymentReversalForm(_IndependentClaimPaymentReviewerFormMixin, forms.Form):
    amount = forms.DecimalField(
        label="مبلغ برگشتی",
        max_digits=16,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    paid_at = forms.DateField(
        label="تاریخ اصلاح",
        required=False,
        input_formats=["%Y-%m-%d", "%Y/%m/%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reason = forms.CharField(label="علت برگشت/اصلاح", max_length=5000, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed_by = forms.ModelChoiceField(
        label="تأییدکننده مستقل",
        queryset=User.objects.none(),
        empty_label="انتخاب تأییدکننده",
    )

    def __init__(self, *args, claim=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if claim and user:
            self._set_reviewers(claim=claim, user=user)
