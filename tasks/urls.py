from django.urls import path
from . import views
urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("new/", views.task_create, name="task_create"),
    path("<int:pk>/", views.task_update, name="task_update"),
]
