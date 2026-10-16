from django.urls import path

from . import cash_views, views

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
    path("caisse/", cash_views.cash_register, name="cash_register"),
    path("caisse/cloturer/", cash_views.cash_close, name="cash_close"),
    path("rapports/", cash_views.reports, name="reports"),
    path("rapports/export.xlsx", cash_views.export_xlsx, name="export_xlsx"),
    path("rapports/recapitulatif.pdf", cash_views.export_pdf, name="export_pdf"),
    path("tarifs/", views.tariffs, name="tariffs"),
    path("tarifs/ajouter/", views.tariff_add, name="tariff_add"),
    path("tarifs/<int:pk>/", views.tariff_row, name="tariff_row"),
]
