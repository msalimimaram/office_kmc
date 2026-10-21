from django.urls import path
from . import views

urlpatterns = [
    path("", views.correspondence_list, name="correspondence_list"),
    path("new/", views.correspondence_create, name="correspondence_create"),
    path("<int:pk>/attachment/", views.correspondence_download, name="correspondence_download"),
]
