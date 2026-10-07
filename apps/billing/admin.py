from django.contrib import admin

from apps.accounts.admin import TenantScopedAdmin

from .models import Invoice, InvoiceItem, MedicalAct


@admin.register(MedicalAct)
class MedicalActAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(TenantScopedAdmin):
    list_display = ("invoice_number", "patient", "total_amount", "status", "cabinet", "created_at")
    list_filter = ("status", "payment_method", "cabinet")
    search_fields = ("invoice_number", "patient__first_name", "patient__last_name")
    readonly_fields = ("invoice_number", "created_at")
    inlines = [InvoiceItemInline]
