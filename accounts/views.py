from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import UserNotification


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    """Clear the forced-change flag only after a successful password change."""

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response



@login_required
def notification_list(request):
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
