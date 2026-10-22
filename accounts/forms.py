"""Login form with cache-backed throttling for repeated failed attempts.

Production deployments with multiple application workers must configure a shared,
atomic cache backend (for example Redis). The default local-memory cache is suitable
only for development and single-process deployments.
"""
import hashlib

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError


LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60


class ThrottledAuthenticationForm(AuthenticationForm):
    """Limit repeated failures per normalized username and client IP."""

    def _attempt_key(self):
        username = (self.cleaned_data.get("username") or self.data.get("username") or "").strip().casefold()
        ip_address = self.request.META.get("REMOTE_ADDR", "unknown")
        digest = hashlib.sha256(f"{username}\0{ip_address}".encode("utf-8")).hexdigest()
        return f"login-failures:{digest}"

    def clean(self):
        key = self._attempt_key()
        if cache.get(key, 0) >= LOGIN_FAILURE_LIMIT:
            raise ValidationError(
                "تعداد تلاش‌های ورود بیش از حد مجاز است. ۱۵ دقیقه دیگر دوباره تلاش کنید.",
                code="login_throttled",
            )

        try:
            cleaned_data = super().clean()
        except ValidationError:
            failures = cache.get(key, 0)
            cache.set(key, failures + 1, timeout=LOGIN_LOCKOUT_SECONDS)
            raise

        cache.delete(key)
        return cleaned_data
