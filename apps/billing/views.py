import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from .models import Invoice
from .services import generate_receipt_pdf


@login_required
def index(request):
    invoices = Invoice.objects.select_related("patient").filter(
        cabinet=request.user.profile.cabinet
    )[:50]
    return render(request, "billing/index.html", {"invoices": invoices})


@login_required
def pay_invoice(request, pk):
    cabinet = request.user.profile.cabinet
    invoice = get_object_or_404(Invoice, pk=pk, cabinet=cabinet)
    toast_message = None
    receipt_url = None
    if request.method == "POST":
        payment_method = request.POST.get("payment_method", Invoice.PaymentMethod.CASH)
        invoice.payment_method = payment_method
        invoice.status = Invoice.Status.PAID
        invoice.paid_at = timezone.now()
        invoice.save(update_fields=["payment_method", "status", "paid_at"])
        toast_message = (
            f"Facture {invoice.invoice_number} encaissée ({invoice.get_payment_method_display()})."
        )
        receipt_url = reverse("billing:invoice_receipt", args=[invoice.pk])

    pending_invoices = Invoice.objects.select_related("patient").filter(
        status=Invoice.Status.PENDING, cabinet=cabinet
    )
    response = render(
        request, "assistant/_pending_invoices.html", {"pending_invoices": pending_invoices}
    )
    if toast_message:
        events = {"toast": {"message": toast_message, "type": "success"}}
        if receipt_url:
            events["receipt-ready"] = {"url": receipt_url}
        response.headers["HX-Trigger"] = json.dumps(events)
    return response


@login_required
def download_receipt_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, cabinet=request.user.profile.cabinet)
    if invoice.status != Invoice.Status.PAID:
        raise Http404("Reçu disponible uniquement après encaissement.")

    pdf_bytes = generate_receipt_pdf(invoice)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="recu_{invoice.invoice_number}.pdf"'
    return response
