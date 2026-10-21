from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from dashboard import views as dashboard_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(template_name="registration/password_change.html", success_url="/"), name="password_change"),
    path("", dashboard_views.home, name="home"),
    path("dashboard/", dashboard_views.home, name="dashboard"),
    path("organizations/", include("organizations.urls")),
    path("insurance/", include("insurance.urls")),
    path("claims/", include("claims.urls")),
    path("requests/", include("requests_portal.urls")),
    path("tasks/", include("tasks.urls")),
    path("imports/", include("imports.urls")),
]
