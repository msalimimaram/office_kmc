from django.urls import path

from . import views


urlpatterns = [
    path("contracts/", views.contract_list, name="contract_list"),
    path("contracts/new/", views.contract_create, name="contract_create"),
    path("contracts/<int:pk>/", views.contract_detail, name="contract_detail"),
    path("contracts/<int:pk>/revisions/new/", views.contract_revision_create, name="contract_revision_create"),
    path("contracts/<int:pk>/terminate/", views.contract_terminate, name="contract_terminate"),
    path(
        "contracts/<int:pk>/revisions/<int:revision_pk>/download/",
        views.contract_revision_download,
        name="contract_revision_download",
    ),
]
