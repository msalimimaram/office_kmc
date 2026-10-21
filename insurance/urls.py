from django.urls import path
from . import views

urlpatterns = [
    path("contracts/", views.contract_list, name="contract_list"),
]
