from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create_patient, name="create_patient"),
]
