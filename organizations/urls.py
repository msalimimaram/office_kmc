from django.urls import path
from . import views
urlpatterns = [path("", views.people_list, name="people_list")]
