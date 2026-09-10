from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.assistant_dashboard, name="assistant_dashboard"),
    path("new/", views.create_appointment, name="create_appointment"),
    path("new/<int:patient_id>/", views.create_appointment, name="create_appointment_for"),
    path("search/", views.patient_search, name="patient_search"),
    path("<int:pk>/advance/", views.advance_status, name="advance_status"),
    path("<int:pk>/whatsapp/<str:action>/", views.whatsapp_action, name="whatsapp_action"),
    path("calendar/", views.appointment_calendar, name="calendar"),
    path("calendar/modal/", views.appointment_modal, name="appointment_modal"),
    path("calendar/<int:pk>/drawer/", views.appointment_drawer, name="appointment_drawer"),
    path("calendar/<int:pk>/vitals/", views.save_intake_vitals, name="save_intake_vitals"),
    path("calendar/<int:pk>/vitals/modal/", views.intake_vitals_modal, name="intake_vitals_modal"),
    path("calendar/create/", views.create_appointment_ajax, name="create_appointment_ajax"),
    path("calendar/<int:pk>/update/", views.update_appointment_ajax, name="update_appointment_ajax"),
    path("calendar/<int:pk>/cancel/", views.cancel_appointment_ajax, name="cancel_appointment_ajax"),
    path("calendar/<int:pk>/advance/", views.calendar_advance_status, name="calendar_advance_status"),
    path("calendar/patients/search/", views.patient_picker_search, name="patient_picker_search"),
    path("calendar/patients/<int:pk>/select/", views.select_patient_for_slot, name="select_patient_for_slot"),
    path("calendar/patients/quick-create/", views.quick_create_patient, name="quick_create_patient"),
]
