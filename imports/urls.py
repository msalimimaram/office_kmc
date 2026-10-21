from django.urls import path
from . import views
urlpatterns = [
    path("claims/", views.claim_import, name="claim_import"),
    path("claims/<int:batch_id>/confirm/", views.claim_import_confirm, name="claim_import_confirm"),
]
