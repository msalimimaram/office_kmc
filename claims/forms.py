from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from accounts.access import has_global_access, has_role, line_codes_for
from accounts.models import RoleAssignment, User
from insurance.models import Insurer, Contract
from organizations.models import Person, PersonEmployment
from .models import Claim, ClaimObjection

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



def company_for_person_on_date(person, service_date):
    employee = person.employee if person.employee_id else person
    history = PersonEmployment.objects.filter(person_id=employee.pk)
    employment = history.filter(
        valid_from__lte=service_date
    ).filter(
        Q(valid_until__isnull=True) | Q(valid_until__gte=service_date)
    ).order_by("-valid_from", "-pk").first()
    if employment:
        return employment.company
    if not history.exists():
        return employee.company or person.company
    return None


class ClaimForm(forms.ModelForm):
    service_date = forms.DateField(
        label="تاریخ خسارت / خدمت",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    registered_date = forms.DateField(
        label="تاریخ ثبت",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = Claim
        fields = [
            "claim_number",
            "source_claim_number",
            "person",
            "contract",
            "service_date",
            "registered_date",
            "service_type",
            "requested_amount",
            "source_reference",
        ]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        contracts = Contract.objects.exclude(
            status__in=[
                Contract.Status.DRAFT,
                Contract.Status.PENDING_APPROVAL,
                Contract.Status.APPROVED,
                Contract.Status.REJECTED,
            ]
        )
        if not has_global_access(user):
            lines = line_codes_for(user, role=RoleAssignment.Role.INSURANCE_SPECIALIST)
            if "*" not in lines:
                contracts = contracts.filter(line__in=lines)
        contracts = contracts.prefetch_related("companies").select_related("insurer").distinct()
        self.fields["contract"].queryset = contracts.order_by("code")
        self.fields["contract"].required = True
        self.fields["registered_date"].initial = timezone.localdate()

        company_ids = set(
            contracts.values_list("companies__pk", flat=True).exclude(companies__pk__isnull=True)
        )
        employment_person_ids = set(
            PersonEmployment.objects.filter(company_id__in=company_ids).values_list("person_id", flat=True)
        )
        historical_person_ids = set(
            Person.objects.filter(company_id__in=company_ids)
            .exclude(pk__in=PersonEmployment.objects.values_list("person_id", flat=True))
            .values_list("pk", flat=True)
        )
        primary_ids = employment_person_ids | historical_person_ids
        dependent_ids = set(
            Person.objects.filter(employee_id__in=primary_ids).values_list("pk", flat=True)
        )
        self.fields["person"].queryset = Person.objects.filter(
            Q(pk__in=primary_ids) | Q(pk__in=dependent_ids),
            is_active=True,
            is_insured=True,
        ).select_related("employee", "company").distinct().order_by("last_name", "first_name")

    def clean(self):
        cleaned = super().clean()
        person = cleaned.get("person")
        contract = cleaned.get("contract")
        service_date = cleaned.get("service_date")
        registered_date = cleaned.get("registered_date")
        if registered_date and registered_date > timezone.localdate():
            self.add_error("registered_date", "تاریخ ثبت نمی‌تواند در آینده باشد.")
        if service_date and registered_date and service_date > registered_date:
            self.add_error("service_date", "تاریخ خدمت نمی‌تواند بعد از تاریخ ثبت پرونده باشد.")
        if person and contract and service_date:
            company = company_for_person_on_date(person, service_date)
            if not company:
                self.add_error(
                    "person",
                    "شرکت محل اشتغال شخص در تاریخ خدمت از سوابق معتبر قابل تعیین نیست.",
                )
            else:
                if not contract.companies.filter(pk=company.pk).exists():
                    self.add_error("contract", "قرارداد انتخاب‌شده در تاریخ خدمت متعلق به شرکت شخص نیست.")
                if not contract.start_date <= service_date <= contract.end_date:
                    self.add_error("contract", "تاریخ خدمت خارج از بازه اعتبار قرارداد انتخاب‌شده است.")
                if not has_global_access(self.user) and not has_role(
                    self.user,
                    RoleAssignment.Role.INSURANCE_SPECIALIST,
                    line_code=contract.line,
                ):
                    self.add_error("contract", "شما برای رشته این قرارداد انتصاب معتبر ندارید.")
        return cleaned


class ClaimAssessmentForm(forms.Form):
    assessed_amount = forms.DecimalField(
        label="مبلغ تأییدشده",
        max_digits=16,
        decimal_places=2,
        min_value=Decimal("0"),
    )
    payable_amount = forms.DecimalField(
        label="مبلغ قابل پرداخت",
        max_digits=16,
        decimal_places=2,
        min_value=Decimal("0"),
    )
    assessment_note = forms.CharField(
        label="یادداشت ارزیابی غیرپزشکی",
        min_length=10,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, claim, **kwargs):
        super().__init__(*args, **kwargs)
        self.claim = claim
        self.fields["assessed_amount"].initial = claim.assessed_amount
        self.fields["payable_amount"].initial = claim.payable_amount
        self.fields["assessment_note"].initial = claim.assessment_note

    def clean(self):
        cleaned = super().clean()
        assessed = cleaned.get("assessed_amount")
        payable = cleaned.get("payable_amount")
        if assessed is not None and assessed > self.claim.requested_amount:
            self.add_error("assessed_amount", "مبلغ تأییدشده نمی‌تواند از مبلغ درخواستی بیشتر باشد.")
        if assessed is not None and payable is not None and payable > assessed:
            self.add_error("payable_amount", "مبلغ قابل پرداخت نمی‌تواند از مبلغ تأییدشده بیشتر باشد.")
        return cleaned



class ClaimDuplicateDeclarationForm(forms.Form):
    source_duplicate_reference = forms.CharField(
        label="شماره پرونده اصلی نزد بیمه‌گر",
        max_length=120,
    )
    source_duplicate_note = forms.CharField(
        label="توضیح رسمی بیمه‌گر درباره تکراری بودن",
        min_length=10,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
