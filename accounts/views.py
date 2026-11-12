from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import UserNotification, RoleAssignment
from .access import active_internal_position_assignments, company_ids_for, has_role, is_insurance_staff


def _can_access_notifications(user):
    has_active_position = active_internal_position_assignments(user).exists()
    return (
        is_insurance_staff(user)
        or has_role(user, RoleAssignment.Role.INSURED_PERSON)
        or has_role(user, RoleAssignment.Role.SUBSIDIARY_REP)
        or has_role(user, RoleAssignment.Role.INSURER_REP)
        or has_active_position
    )


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    """Clear the forced-change flag only after a successful password change."""

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response



@login_required
def notification_list(request):
    if not _can_access_notifications(request.user):
        raise PermissionDenied("شما مجاز به مشاهده اعلان‌ها نیستید.")
    notifications = UserNotification.objects.filter(
        recipient=request.user
    ).order_by("-created_at", "-pk")
    page_obj = Paginator(notifications, 30).get_page(request.GET.get("page"))
    return render(request, "accounts/notification_list.html", {
        "notifications": page_obj.object_list,
        "page_obj": page_obj,
    })


@login_required
@require_POST
def notification_mark_read(request, pk):
    if not _can_access_notifications(request.user):
        raise PermissionDenied("شما مجاز به مدیریت اعلان‌ها نیستید.")
    notification = get_object_or_404(
        UserNotification,
        pk=pk,
        recipient=request.user,
    )
    notification.mark_read(user=request.user)
    target = notification.target_url
    if target.startswith("/") and not target.startswith("//"):
        return redirect(target)
    return redirect("notification_list")



@login_required
@require_POST
def select_active_company(request):
    """Change the active subsidiary context without expanding authorization."""
    allowed_company_ids = company_ids_for(
        request.user, role=RoleAssignment.Role.SUBSIDIARY_REP
    )
    if not allowed_company_ids:
        raise PermissionDenied("برای این حساب محدوده نمایندگی شرکت فعالی تعریف نشده است.")
    try:
        selected_company_id = int(request.POST.get("company_id", ""))
    except (TypeError, ValueError):
        raise PermissionDenied("شرکت انتخاب‌شده معتبر نیست.")
    if selected_company_id not in allowed_company_ids:
        raise PermissionDenied("انتخاب شرکت خارج از محدوده انتصاب معتبر شماست.")

    request.session["active_company_id"] = selected_company_id
    request.session.modified = True
    target = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        target = reverse("dashboard")
    return redirect(target)
