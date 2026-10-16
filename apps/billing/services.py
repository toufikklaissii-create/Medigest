from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.clinical.services import LETTERHEAD, letterhead_context
from apps.common.pdf import render_pdf, save_pdf_copy
from apps.common.templatetags.medigest_format import dh

from .amount_words import montant_en_lettres
from .models import Invoice, Payment, PaymentMethod

METHODS_WITH_REFERENCE = {PaymentMethod.CHECK, PaymentMethod.TRANSFER}
METHOD_ICONS = {
    PaymentMethod.CASH: "banknote",
    PaymentMethod.CARD: "credit-card",
    PaymentMethod.CHECK: "file-pen-line",
    PaymentMethod.TRANSFER: "landmark",
}
# (valeur, libellé, icône Lucide) pour les raccourcis d'encaissement.
PAYMENT_SHORTCUTS = [(value, label, METHOD_ICONS[value]) for value, label in PaymentMethod.choices]


class BillingError(ValueError):
    """Opération de facturation refusée : le message est affiché tel quel à l'utilisateur."""


def parse_amount(value):
    """« 1 250,50 » ou « 1250.5 » → Decimal('1250.50') ; None si vide ou illisible."""
    text = str(value or "").replace(" ", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        amount = Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def pending_invoices_queryset(cabinet):
    """Factures restant à encaisser (totalement ou en partie), pour l'accueil."""
    return (
        Invoice.objects.filter(
            cabinet=cabinet, status__in=[Invoice.Status.PENDING, Invoice.Status.PARTIAL]
        )
        .select_related("patient")
        .prefetch_related("payments")
    )


def record_payment(invoice, amount, method, user, reference="", paid_at=None):
    """Enregistre un encaissement, total ou partiel, sans jamais dépasser le reste dû."""
    if method not in PaymentMethod.values:
        raise BillingError("Choisissez un mode de paiement.")
    reference = (reference or "").strip()
    if method in METHODS_WITH_REFERENCE and not reference:
        label = "chèque" if method == PaymentMethod.CHECK else "virement"
        raise BillingError(f"Indiquez le numéro du {label}.")

    with transaction.atomic():
        # Verrou sur la facture : deux encaissements simultanés ne peuvent pas dépasser le reste dû.
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.is_cancelled:
            raise BillingError("Cette facture est annulée : aucun encaissement possible.")
        balance = invoice.balance_due
        if balance <= 0:
            raise BillingError("Cette facture est déjà soldée.")
        if amount is None:
            amount = balance
        if amount <= 0:
            raise BillingError("Le montant encaissé doit être supérieur à zéro.")
        if amount > balance:
            raise BillingError(f"Le montant dépasse le reste dû ({dh(balance)}).")
        payment = Payment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference if method in METHODS_WITH_REFERENCE else "",
            paid_at=paid_at or timezone.now(),
            received_by=user,
        )
        invoice.refresh_payment_status()
    return payment


def cancel_invoice(invoice, reason, user):
    """Annule une facture non encaissée : le numéro reste attribué, la ligne n'est jamais supprimée."""
    reason = (reason or "").strip()
    if not reason:
        raise BillingError("Indiquez le motif de l'annulation.")
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.is_cancelled:
            raise BillingError("Cette facture est déjà annulée.")
        if invoice.payments.exists():
            raise BillingError("Facture déjà encaissée (en tout ou partie) : annulation impossible.")
        invoice.status = Invoice.Status.CANCELLED
        invoice.cancel_reason = reason
        invoice.cancelled_at = timezone.now()
        invoice.cancelled_by = user
        invoice.save(update_fields=["status", "cancel_reason", "cancelled_at", "cancelled_by"])
    return invoice


def report_discrepancy(invoice, message, author):
    """« Signaler un écart » : tâche pour la doctoresse du cabinet, sans toucher à la facture."""
    from apps.accounts.models import Profile
    from apps.communications.models import Task

    doctor_profile = (
        Profile.objects.filter(cabinet=invoice.cabinet, role=Profile.Role.DOCTOR)
        .select_related("user").order_by("pk").first()
    )
    if doctor_profile is None:
        raise BillingError("Aucune doctoresse n'est rattachée à ce cabinet.")
    message = (message or "").strip()
    patient = invoice.patient
    description = (
        f"Facture {invoice.invoice_number} — Mme {patient.first_name} {patient.last_name}\n"
        f"Montant facturé : {dh(invoice.total_amount)} · reste dû : {dh(invoice.balance_due)}"
    )
    if message:
        description += f"\n\n{message}"
    return Task.objects.create(
        cabinet=invoice.cabinet,
        author=author,
        assignee=doctor_profile.user,
        patient=patient,
        title=f"Écart de facturation — {invoice.invoice_number}",
        description=description,
    )


def generate_invoice_pdf(invoice, save_copy=True):
    patient = invoice.patient
    payments = list(invoice.payments.all())
    pdf_bytes = render_pdf(
        "pdf/invoice.html",
        {
            **letterhead_context(patient, invoice.created_at),
            "invoice": invoice,
            "items": invoice.items.select_related("act"),
            "payments": payments,
            "amount_paid": sum((p.amount for p in payments), Decimal("0")),
            "amount_words": montant_en_lettres(invoice.total_amount),
        },
        background=LETTERHEAD,
    )
    if save_copy:
        save_pdf_copy(patient, "facture", pdf_bytes, reference=invoice.invoice_number)
    return pdf_bytes


def generate_receipt_pdf(payment, save_copy=True):
    """Reçu d'UN paiement (un reçu par encaissement, partiel ou non)."""
    invoice = payment.invoice
    patient = invoice.patient
    pdf_bytes = render_pdf(
        "pdf/receipt.html",
        {
            **letterhead_context(patient, payment.paid_at),
            "invoice": invoice,
            "payment": payment,
            "amount_words": montant_en_lettres(payment.amount),
        },
        background=LETTERHEAD,
    )
    if save_copy:
        save_pdf_copy(patient, "recu", pdf_bytes, reference=payment.receipt_number)
    return pdf_bytes
