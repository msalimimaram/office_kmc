from django.urls import path

from . import views

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("new/", views.report_create, name="report_create"),
    path("<int:pk>/", views.report_detail, name="report_detail"),
]
