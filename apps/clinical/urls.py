from django.urls import path

from . import modeles_views, views

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
        "consultation/<int:appointment_id>/pdf/prescription/<str:part>/",
        views.download_prescription_pdf,
        name="prescription_part_pdf",
    ),
    path("modeles-ordonnance/", modeles_views.modeles_ordonnance, name="modeles_ordonnance"),
    path("modeles-ordonnance/ajouter/", modeles_views.modele_add, name="modele_add"),
    path("modeles-ordonnance/<int:pk>/", modeles_views.modele_card, name="modele_card"),
    path("modeles-ordonnance/<int:pk>/dupliquer/", modeles_views.modele_duplicate, name="modele_duplicate"),
    path("modeles-ordonnance/<int:pk>/supprimer/", modeles_views.modele_delete, name="modele_delete"),
    path("modeles-courrier/", modeles_views.modeles_courrier, name="modeles_courrier"),
    path("modeles-courrier/ajouter/", modeles_views.courrier_add, name="courrier_add"),
    path("modeles-courrier/<int:pk>/", modeles_views.courrier_card, name="courrier_card"),
    path("modeles-courrier/<int:pk>/dupliquer/", modeles_views.courrier_duplicate, name="courrier_duplicate"),
    path("modeles-courrier/<int:pk>/supprimer/", modeles_views.courrier_delete, name="courrier_delete"),
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
    path("documents/<int:pk>/fichier/", views.serve_patient_document, name="patient_document_file"),
    path(
        "consultation/<int:appointment_id>/pdf/dossier/",
        views.download_patient_record_pdf,
        name="patient_record_pdf",
    ),
]
