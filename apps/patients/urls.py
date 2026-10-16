from django.urls import path

from apps.clinical.views import download_full_patient_archive

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create_patient, name="create_patient"),
    path("<int:pk>/edit/", views.edit_patient, name="edit_patient"),
    path("<int:pk>/documents/", views.patient_documents, name="patient_documents"),
    path("<int:pk>/documents/telephone/", views.phone_upload_qr, name="phone_upload_qr"),
    path("envoi/<str:token>/", views.phone_upload, name="phone_upload"),
    path("<int:patient_id>/archive/", download_full_patient_archive, name="patient_full_archive"),
]
