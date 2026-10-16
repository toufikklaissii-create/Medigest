import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.common.templatetags.medigest_format import dh

from .models import Invoice, MedicalAct, Payment, PaymentMethod
from .services import (
    METHODS_WITH_REFERENCE,
    PAYMENT_SHORTCUTS,
    BillingError,
    cancel_invoice,
    generate_invoice_pdf,
    generate_receipt_pdf,
    parse_amount,
    pending_invoices_queryset,
    record_payment,
    report_discrepancy,
)

STATUS_FILTERS = [
    ("", "Toutes"),
    (Invoice.Status.PENDING, "À encaisser"),
    (Invoice.Status.PARTIAL, "Partielle"),
    (Invoice.Status.PAID, "Payée"),
    (Invoice.Status.CANCELLED, "Annulée"),
]
PAGE_SIZE = 20


def _hx_trigger(response, **events):
    response.headers["HX-Trigger"] = json.dumps(events)
    return response


def _toast(message, type_="success"):
    return {"message": message, "type": type_}


def _cabinet_invoices(request):
    return Invoice.objects.filter(cabinet=request.user.profile.cabinet)


# ── Page Facturation ─────────────────────────────────────────────────────────

def _invoice_list_context(request):
    status = request.GET.get("statut", "")
    if status not in Invoice.Status.values:
        status = ""
    query = request.GET.get("q", "").strip()

    invoices = _cabinet_invoices(request).select_related("patient")
    for term in query.split():
        invoices = invoices.filter(
            Q(invoice_number__icontains=term)
            | Q(patient__first_name__icontains=term)
            | Q(patient__last_name__icontains=term)
            | Q(patient__patient_number__icontains=term)
        )
    counts = dict(invoices.values_list("status").annotate(n=Count("pk")).values_list("status", "n"))
    if status:
        invoices = invoices.filter(status=status)

    page = Paginator(invoices.prefetch_related("payments").order_by("-created_at", "-pk"), PAGE_SIZE)
    page_obj = page.get_page(request.GET.get("page"))
    return {
        "page_obj": page_obj,
        "invoices": page_obj.object_list,
        "status": status,
        "query": query,
        "status_filters": [
            (value, label, sum(counts.values()) if not value else counts.get(value, 0))
            for value, label in STATUS_FILTERS
        ],
    }


@login_required
def index(request):
    context = _invoice_list_context(request)
    if request.headers.get("HX-Request") and request.GET.get("partial") == "table":
        return render(request, "billing/_invoice_table.html", {**context, "is_partial": True})
    return render(request, "billing/index.html", context)


@login_required
def pending_invoices(request):
    return render(
        request,
        "assistant/_pending_invoices.html",
        {"pending_invoices": pending_invoices_queryset(request.user.profile.cabinet)},
    )


# ── Encaissement ─────────────────────────────────────────────────────────────

def _pay_modal(request, invoice, **extra):
    method = extra.pop("method", None) or request.GET.get("method") or PaymentMethod.CASH
    return render(
        request,
        "billing/_pay_modal.html",
        {
            "invoice": invoice,
            "method": method if method in PaymentMethod.values else PaymentMethod.CASH,
            "methods": PAYMENT_SHORTCUTS,
            "methods_with_reference_json": json.dumps(sorted(METHODS_WITH_REFERENCE)),
            # Saisie à la française : « 350,00 ».
            "amount": extra.pop("amount", None) or f"{invoice.balance_due:.2f}".replace(".", ","),
            **extra,
        },
    )


@login_required
def pay_invoice(request, pk):
    """GET : modale d'encaissement. POST : enregistre un paiement (total ou partiel).

    Le montant de la facture n'est jamais modifiable ici : seul le montant encaissé est saisi,
    borné au reste dû.
    """
    invoice = get_object_or_404(_cabinet_invoices(request).select_related("patient"), pk=pk)
    if request.method != "POST":
        return _pay_modal(request, invoice)

    raw_amount = request.POST.get("amount", "")
    amount = parse_amount(raw_amount)
    method = request.POST.get("payment_method", PaymentMethod.CASH)
    reference = request.POST.get("reference", "")
    try:
        if raw_amount.strip() and amount is None:
            raise BillingError("Montant illisible : saisissez par exemple 250 ou 250,50.")
        payment = record_payment(invoice, amount, method, request.user, reference=reference)
    except BillingError as error:
        return _pay_modal(
            request, invoice, error=str(error), method=method, amount=raw_amount or None,
            reference=reference,
        )

    invoice.refresh_from_db()
    receipt_url = reverse("billing:payment_receipt", args=[payment.pk])
    if invoice.status == Invoice.Status.PAID:
        message = f"Facture {invoice.invoice_number} soldée ({payment.get_method_display()})."
    else:
        message = f"{dh(payment.amount)} encaissés · reste {dh(invoice.balance_due)}."
    response = render(
        request, "billing/_pay_modal.html",
        {"invoice": invoice, "payment": payment, "receipt_url": receipt_url, "done": True},
    )
    return _hx_trigger(
        response, toast=_toast(message), **{"invoice-paid": True, "receipt-ready": {"url": receipt_url}}
    )


@login_required
@require_POST
def report_invoice_discrepancy(request, pk):
    invoice = get_object_or_404(_cabinet_invoices(request).select_related("patient"), pk=pk)
    try:
        report_discrepancy(invoice, request.POST.get("message", ""), request.user)
    except BillingError as error:
        return _hx_trigger(HttpResponse(""), toast=_toast(str(error), "error"))
    return _hx_trigger(
        HttpResponse(""),
        toast=_toast("Écart signalé à la doctoresse."),
        **{"discrepancy-sent": True, "tasks-refresh": True},
    )


@login_required
@role_required("doctor")
@require_POST
def cancel_invoice_view(request, pk):
    invoice = get_object_or_404(_cabinet_invoices(request), pk=pk)
    try:
        invoice = cancel_invoice(invoice, request.POST.get("reason", ""), request.user)
    except BillingError as error:
        return _hx_trigger(HttpResponse(str(error), status=200), toast=_toast(str(error), "error"))
    return _hx_trigger(
        HttpResponse(""),
        toast=_toast(f"Facture {invoice.invoice_number} annulée. Son numéro reste attribué."),
        **{"invoice-paid": True},
    )


# ── Documents ────────────────────────────────────────────────────────────────

def _pdf_response(pdf_bytes, filename):
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def invoice_pdf(request, pk):
    invoice = get_object_or_404(_cabinet_invoices(request).select_related("patient"), pk=pk)
    return _pdf_response(generate_invoice_pdf(invoice), f"facture_{invoice.invoice_number}.pdf")


@login_required
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related("invoice__patient"),
        pk=pk, invoice__cabinet=request.user.profile.cabinet,
    )
    return _pdf_response(generate_receipt_pdf(payment), f"recu_{payment.receipt_number}.pdf")


@login_required
def download_receipt_pdf(request, pk):
    """Reçu du dernier paiement de la facture (lien historique « Reçu »)."""
    invoice = get_object_or_404(_cabinet_invoices(request), pk=pk)
    payment = invoice.payments.order_by("-paid_at", "-pk").first()
    if payment is None:
        raise Http404("Reçu disponible uniquement après encaissement.")
    return payment_receipt(request, payment.pk)


# ── Tarifs (doctoresse uniquement) ───────────────────────────────────────────

def _cabinet_acts(request):
    return MedicalAct.objects.filter(cabinet=request.user.profile.cabinet)


def _act_from_post(request, act):
    """Applique le POST sur l'acte ; renvoie un dict d'erreurs (vide si valide)."""
    errors = {}
    act.code = request.POST.get("code", "").strip().upper()[:30]
    act.name = request.POST.get("name", "").strip()[:150]
    price = parse_amount(request.POST.get("price"))
    if not act.code:
        errors["code"] = "Code obligatoire."
    if not act.name:
        errors["name"] = "Libellé obligatoire."
    if price is None or price < 0:
        errors["price"] = "Prix invalide."
    else:
        act.price = price
    act.is_active = request.POST.get("is_active") == "on"
    act.is_quick_exam = request.POST.get("is_quick_exam") == "on"
    duplicate = _cabinet_acts(request).filter(code=act.code).exclude(pk=act.pk).exists()
    if act.code and duplicate:
        errors["code"] = "Ce code existe déjà."
    return errors


@login_required
@role_required("doctor")
def tariffs(request):
    return render(request, "billing/tariffs.html", {"acts": _cabinet_acts(request).order_by("name")})


@login_required
@role_required("doctor")
def tariff_row(request, pk):
    """GET : ligne en lecture (?edit=1 : en édition). POST : enregistre la ligne."""
    act = get_object_or_404(_cabinet_acts(request), pk=pk)
    if request.method != "POST":
        template = "billing/_tariff_row_edit.html" if request.GET.get("edit") else "billing/_tariff_row.html"
        return render(request, template, {"act": act})
    errors = _act_from_post(request, act)
    if errors:
        return render(request, "billing/_tariff_row_edit.html", {"act": act, "errors": errors})
    try:
        act.save()
    except IntegrityError:
        return render(request, "billing/_tariff_row_edit.html", {"act": act, "errors": {"code": "Ce code existe déjà."}})
    response = render(request, "billing/_tariff_row.html", {"act": act, "flash": True})
    return _hx_trigger(response, toast=_toast(f"Tarif « {act.name} » enregistré."))


@login_required
@role_required("doctor")
@require_POST
def tariff_add(request):
    act = MedicalAct(cabinet=request.user.profile.cabinet)
    errors = _act_from_post(request, act)
    if not errors:
        try:
            act.save()
        except IntegrityError:
            errors = {"code": "Ce code existe déjà."}
    if errors:
        response = render(request, "billing/_tariff_add_form.html", {"errors": errors, "form": request.POST})
        response.headers["HX-Retarget"] = "#tariff-add-form"
        response.headers["HX-Reswap"] = "outerHTML"
        return response
    response = render(request, "billing/_tariff_row.html", {"act": act, "flash": True})
    return _hx_trigger(response, toast=_toast(f"Acte « {act.name} » ajouté."), **{"tariff-added": True})
