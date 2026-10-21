from django.shortcuts import redirect
from django.urls import reverse


class RequirePasswordChangeMiddleware:
    """Force newly provisioned users to replace their initial password."""
    exempt_names = {"password_change", "logout"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            if request.resolver_match is None or request.resolver_match.url_name not in self.exempt_names:
                return redirect("password_change")
        return self.get_response(request)
