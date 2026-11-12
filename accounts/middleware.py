from django.shortcuts import redirect
from django.urls import reverse


class RequirePasswordChangeMiddleware:
    """Force newly provisioned users to replace their initial password."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            exempt_paths = {reverse("password_change"), reverse("logout")}
            if request.path_info not in exempt_paths and not request.path_info.startswith("/static/"):
                return redirect("password_change")
        return self.get_response(request)


class RestrictAdminAccessMiddleware:
    """Keep the Django administration site limited to active system administrators."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            request.path_info.startswith("/admin/")
            and user is not None
            and user.is_authenticated
        ):
            from accounts.access import has_global_access

            # Technical Django flags never replace a current business-role grant.
            allowed = has_global_access(user)
            if not allowed:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied("دسترسی به پنل مدیریت فقط برای مدیر سامانه یا رئیس اداره بیمه مجاز است.")
        return self.get_response(request)
