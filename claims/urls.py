from django.urls import path
from . import views
urlpatterns = [
    path("", views.claim_list, name="claim_list"),
    path("<int:pk>/", views.claim_detail, name="claim_detail"),
    path("<int:pk>/objections/<int:objection_pk>/review/", views.claim_objection_review, name="claim_objection_review"),
    path("<int:pk>/payments/new/", views.claim_payment_create, name="claim_payment_create"),
    path("<int:pk>/payments/<int:payment_pk>/reverse/", views.claim_payment_reverse, name="claim_payment_reverse"),
]
