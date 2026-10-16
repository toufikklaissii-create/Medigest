from django.urls import path

from . import views

app_name = "clinical"

urlpatterns = [
    path("", views.doctor_dashboard, name="doctor_dashboard"),
    path("queue/", views.doctor_queue, name="doctor_queue"),
    path("patient/<int:patient_id>/", views.patient_file, name="patient_file"),
    path("consultation/<int:appointment_id>/", views.consultation_detail, name="consultation_detail"),
    path(
        "consultation/<int:appointment_id>/unlock/",
        views.unlock_consultation,
        name="unlock_consultation",
    ),
    path(
        "consultation/<int:appointment_id>/autosave/",
        views.autosave_consultation,
        name="autosave_consultation",
    ),
    path(
        "consultation/<int:appointment_id>/pdf/prescription/",
        views.download_prescription_pdf,
        name="prescription_pdf",
    ),
    path(
        "consultation/<int:appointment_id>/pdf/report/",
        views.download_report_pdf,
        name="report_pdf",
    ),
    path(
        "consultation/<int:appointment_id>/pdf/letter/<str:letter_type>/",
        views.download_letter_pdf,
        name="letter_pdf",
    ),
    path(
        "consultation/<int:appointment_id>/documents/upload/",
        views.upload_patient_document,
        name="upload_patient_document",
    ),
    path(
        "consultation/<int:appointment_id>/pdf/dossier/",
        views.download_patient_record_pdf,
        name="patient_record_pdf",
    ),
]
