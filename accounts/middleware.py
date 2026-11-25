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
            from accounts.models import RoleAssignment
            from django.core.exceptions import PermissionDenied

            # The technical superuser receives a narrowly scoped, one-time
            # bootstrap route. It cannot browse or operate other Django admin
            # models while choosing the first operational System Admin.
            bootstrap_available = not RoleAssignment.objects.filter(
                role=RoleAssignment.Role.SYSTEM_ADMIN
            ).exists()
            if user.is_superuser and bootstrap_available and not has_global_access(user):
                if request.path_info == "/admin/":
                    return redirect("/admin/accounts/roleassignment/add/")
                allowed_bootstrap_paths = {
                    "/admin/accounts/roleassignment/add/",
                    "/admin/jsi18n/",
                }
                is_role_assignment_autocomplete = (
                    request.path_info == "/admin/autocomplete/"
                    and request.GET.get("app_label") == "accounts"
                    and request.GET.get("model_name") == "roleassignment"
                    and request.GET.get("field_name") == "user"
                )
                if (
                    request.path_info not in allowed_bootstrap_paths
                    and not is_role_assignment_autocomplete
                ):
                    raise PermissionDenied(
                        "حساب سوپریوزر راه‌انداز فقط به فرم انتخاب نخستین مدیر سامانه دسترسی دارد."
                    )
                return self.get_response(request)

            if not has_global_access(user):
                raise PermissionDenied(
                    "دسترسی به پنل مدیریت فقط برای مدیر سامانه یا رئیس اداره بیمه مجاز است."
                )
        return self.get_response(request)
