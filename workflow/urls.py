from django.urls import path

from . import views

urlpatterns = [
    path("", views.workflow_case_list, name="workflow_case_list"),
    path("<int:pk>/", views.workflow_case_detail, name="workflow_case_detail"),
]
