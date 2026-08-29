from django.contrib import admin

from .models import Consultation, ConsultationAct, Document


class ConsultationActInline(admin.TabularInline):
    model = ConsultationAct
    extra = 0


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0


@admin.register(Consultation)
class ConsultationAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("patient__first_name", "patient__last_name")
    inlines = [ConsultationActInline, DocumentInline]
