from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "date", "status", "whatsapp_status")
    list_filter = ("status", "whatsapp_status")
    search_fields = ("patient__first_name", "patient__last_name", "patient__patient_number")
