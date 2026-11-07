from django.urls import path
from . import views
urlpatterns = [
    path("", views.people_list, name="people_list"),
    path("leadership-titles/", views.company_leadership_titles, name="company_leadership_titles"),
]
