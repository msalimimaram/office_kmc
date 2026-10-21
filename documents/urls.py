from django.urls import path
from . import views

urlpatterns = [
    path("", views.document_list, name="document_list"),
    path("upload/", views.document_upload, name="document_upload"),
    path("<int:pk>/download/", views.document_download, name="document_download"),
]
