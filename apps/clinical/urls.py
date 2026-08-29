from django.urls import path

from . import views

app_name = "clinical"

urlpatterns = [
    path("", views.doctor_dashboard, name="doctor_dashboard"),
    path("consultation/<int:appointment_id>/", views.consultation_detail, name="consultation_detail"),
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
]
