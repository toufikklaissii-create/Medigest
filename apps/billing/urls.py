from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.index, name="index"),
    path("en-attente/", views.pending_invoices, name="pending_invoices"),
    path("<int:pk>/encaisser/", views.pay_invoice, name="pay_invoice"),
    path("<int:pk>/ecart/", views.report_invoice_discrepancy, name="report_discrepancy"),
    path("<int:pk>/annuler/", views.cancel_invoice_view, name="cancel_invoice"),
    path("<int:pk>/facture/", views.invoice_pdf, name="invoice_pdf"),
    path("<int:pk>/receipt/", views.download_receipt_pdf, name="invoice_receipt"),
    path("paiements/<int:pk>/recu/", views.payment_receipt, name="payment_receipt"),
    path("tarifs/", views.tariffs, name="tariffs"),
    path("tarifs/ajouter/", views.tariff_add, name="tariff_add"),
    path("tarifs/<int:pk>/", views.tariff_row, name="tariff_row"),
]
