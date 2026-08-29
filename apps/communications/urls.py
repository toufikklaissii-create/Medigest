from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("", views.index, name="index"),
    path("tasks/", views.tasks_panel, name="tasks_panel"),
    path("tasks/create/", views.create_task, name="create_task"),
    path("tasks/<int:pk>/toggle/", views.toggle_task, name="toggle_task"),
]
