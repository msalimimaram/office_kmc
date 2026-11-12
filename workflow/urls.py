from django.urls import path

from . import views

urlpatterns = [
    path("", views.workflow_case_list, name="workflow_case_list"),
    path("<int:pk>/", views.workflow_case_detail, name="workflow_case_detail"),
    path("<int:pk>/satisfaction/", views.workflow_satisfaction_submit, name="workflow_satisfaction_submit"),
    path("<int:pk>/satisfaction/submitted/", views.workflow_satisfaction_submitted, name="workflow_satisfaction_submitted"),
]
