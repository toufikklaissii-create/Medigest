from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/pay/", views.pay_invoice, name="pay_invoice"),
    path("<int:pk>/receipt/", views.download_receipt_pdf, name="invoice_receipt"),
]
