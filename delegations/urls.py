from django.urls import path

from . import views

urlpatterns = [
    path("inbox/", views.delegation_inbox, name="delegation_inbox"),
    path("manage/", views.delegation_management, name="delegation_management"),
]
