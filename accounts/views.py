from django.contrib.auth import views as auth_views


class RequiredPasswordChangeView(auth_views.PasswordChangeView):
    """Clear the forced-change flag only after a successful password change."""

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=["must_change_password"])
        return response
