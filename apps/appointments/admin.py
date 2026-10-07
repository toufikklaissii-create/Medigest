from django.contrib import admin

from apps.accounts.admin import TenantScopedAdmin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(TenantScopedAdmin):
    list_display = ("patient", "date", "status", "whatsapp_status", "cabinet")
    list_filter = ("status", "whatsapp_status", "cabinet")
    search_fields = ("patient__first_name", "patient__last_name", "patient__patient_number")
