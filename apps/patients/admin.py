from django.contrib import admin

from apps.accounts.admin import TenantScopedAdmin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(TenantScopedAdmin):
    list_display = ("patient_number", "first_name", "last_name", "phone", "cabinet", "created_at")
    list_filter = ("cabinet",)
    search_fields = ("patient_number", "first_name", "last_name", "cin", "phone")
    readonly_fields = ("patient_number", "created_at")
