"""Login form with cache-backed throttling for repeated failed attempts.

Production deployments with multiple application workers must configure a shared,
atomic cache backend (for example Redis). The default local-memory cache is suitable
only for development and single-process deployments.
"""
import hashlib

from django.contrib.auth.forms import AuthenticationForm
from django import forms
from django.utils import timezone
from accounts.models import OrganizationalPosition
from insurance.models import InsuranceLine
from django.core.cache import cache
from django.core.exceptions import ValidationError

from .access import is_portal_login_eligible


LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


class ThrottledAuthenticationForm(AuthenticationForm):
    """Limit repeated failures per normalized username and client IP."""

    def _attempt_key(self):
        username = (self.cleaned_data.get("username") or self.data.get("username") or "").strip().casefold()
        ip_address = self.request.META.get("REMOTE_ADDR", "unknown")
        digest = hashlib.sha256(f"{username}\0{ip_address}".encode("utf-8")).hexdigest()
        return f"login-failures:{digest}"

    def _record_failure(self, key):
        # Use the cache backend's increment operation where possible so shared
        # caches can update counters atomically across application workers.
        if not cache.add(key, 1, timeout=LOGIN_LOCKOUT_SECONDS):
            try:
                cache.incr(key)
            except ValueError:
                # The key may have expired between add/get and increment.
                cache.add(key, 1, timeout=LOGIN_LOCKOUT_SECONDS)

    def clean(self):
        from organizations.models import normalize_national_id

        submitted_username = self.cleaned_data.get("username") or ""
        normalized_username = normalize_national_id(submitted_username)
        if len(normalized_username) == 10 and normalized_username.isdigit():
            self.cleaned_data["username"] = normalized_username
        key = self._attempt_key()
        if cache.get(key, 0) >= LOGIN_FAILURE_LIMIT:
            raise ValidationError(
                "تعداد تلاش‌های ورود بیش از حد مجاز است. ۱۵ دقیقه دیگر دوباره تلاش کنید.",
                code="login_throttled",
            )

        try:
            cleaned_data = super().clean()
        except ValidationError:
            self._record_failure(key)
            raise

        authenticated_user = self.get_user()
        if not is_portal_login_eligible(authenticated_user):
            raise ValidationError(
                "این حساب کاربری انتصاب عملیاتی معتبر یا سابقه بیمه‌ای مجاز برای ورود به پرتال ندارد.",
                code="account_not_eligible",
            )

        cache.delete(key)
        return cleaned_data


class PersonnelPositionAssignmentForm(forms.Form):
    """Select an internal post and validity period for a roster person."""

    position = forms.ModelChoiceField(
        queryset=OrganizationalPosition.objects.none(),
        label="سمت سازمانی",
    )
    line_code = forms.ChoiceField(
        choices=(("", "بدون رشته"),) + tuple(InsuranceLine.choices),
        required=False,
        label="رشته بیمه",
    )
    valid_from = forms.DateField(
        label="شروع اعتبار",
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    valid_until = forms.DateField(
        label="پایان اعتبار",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    reason = forms.CharField(
        label="دلیل انتصاب",
        min_length=5,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["position"].queryset = OrganizationalPosition.objects.filter(
            is_active=True,
            unit__is_active=True,
            unit__company__isnull=True,
        ).select_related("unit")

    def clean(self):
        cleaned = super().clean()
        position = cleaned.get("position")
        line_code = cleaned.get("line_code")
        valid_from = cleaned.get("valid_from")
        valid_until = cleaned.get("valid_until")
        reason = (cleaned.get("reason") or "").strip()
        if valid_from and valid_until and valid_until < valid_from:
            self.add_error("valid_until", "پایان اعتبار نمی‌تواند قبل از شروع اعتبار باشد.")
        if position:
            if position.code == "department-head":
                if line_code:
                    self.add_error("line_code", "برای سمت رئیس اداره بیمه، رشته بیمه انتخاب نمی‌شود.")
                cleaned["line_code"] = ""
            elif not line_code:
                self.add_error("line_code", "برای سمت‌های تخصصی و سرپرستی، رشته بیمه الزامی است.")
        if reason and len(reason) < 5:
            self.add_error("reason", "دلیل انتصاب باید حداقل پنج نویسه داشته باشد.")
        cleaned["reason"] = reason
        return cleaned
