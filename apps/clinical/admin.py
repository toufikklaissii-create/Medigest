from django.contrib import admin

from apps.accounts.admin import TenantScopedAdmin

from .models import Consultation, ConsultationAct, Document, PatientDocument


class ConsultationActInline(admin.TabularInline):
    model = ConsultationAct
    extra = 0


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0


@admin.register(Consultation)
class ConsultationAdmin(TenantScopedAdmin):
    list_display = ("patient", "doctor", "status", "cabinet", "created_at")
    list_filter = ("status", "cabinet")
    search_fields = ("patient__first_name", "patient__last_name")
    inlines = [ConsultationActInline, DocumentInline]


@admin.register(PatientDocument)
class PatientDocumentAdmin(TenantScopedAdmin):
    list_display = ("title", "patient", "document_type", "cabinet", "created_at")
    list_filter = ("document_type", "cabinet")
    search_fields = ("title", "patient__first_name", "patient__last_name")
