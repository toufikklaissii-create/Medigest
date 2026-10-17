from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import Cabinet
from apps.patients.models import Patient


class MedicalAct(models.Model):
    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="medical_acts", null=True, blank=True
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    is_quick_exam = models.BooleanField(
        "Examen complémentaire rapide", default=False
    )
    # Prix libre : saisi par la doctoresse à chaque consultation (champ vide, obligatoire).
    prix_libre = models.BooleanField("Prix libre", default=False)

    class Meta:
        verbose_name = "Acte médical"
        verbose_name_plural = "Actes médicaux"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["cabinet", "code"], name="unique_act_code_per_cabinet"),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Espèces"
    CARD = "card", "Carte"
    CHECK = "check", "Chèque"
    TRANSFER = "transfer", "Virement"


class Invoice(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "À encaisser"
        PARTIAL = "partial", "Partielle"
        PAID = "paid", "Payée"
        CANCELLED = "cancelled", "Annulée"

    PaymentMethod = PaymentMethod

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="invoices", null=True, blank=True
    )
    invoice_number = models.CharField(max_length=20, editable=False)
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="invoices"
    )
    # Montant net dû : somme des lignes − remise (0 si gratuit). Fixé par la doctoresse uniquement.
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField("Remise", max_digits=10, decimal_places=2, default=0)
    is_free = models.BooleanField("Gratuit / contrôle", default=False)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    # Mode et date du dernier paiement (le détail vit dans Payment).
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, blank=True
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField("Motif d'annulation", blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cabinet", "invoice_number"], name="unique_invoice_number_per_cabinet"
            ),
        ]

    def __str__(self):
        return self.invoice_number

    def save(self, *args, **kwargs):
        if self.invoice_number:
            super().save(*args, **kwargs)
            return
        # Number generation and INSERT share one transaction holding the cabinet
        # row lock, so two concurrent invoices can't read the same Max().
        with transaction.atomic():
            self.invoice_number = self._generate_invoice_number(self.cabinet_id)
            super().save(*args, **kwargs)

    @classmethod
    def _generate_invoice_number(cls, cabinet_id):
        """Next FAC-<year>-NNNN for this cabinet. Must run inside transaction.atomic()."""
        if cabinet_id is not None:
            Cabinet.objects.select_for_update().filter(pk=cabinet_id).first()
        year = timezone.now().year
        prefix = f"FAC-{year}-"
        last = (
            cls.objects.filter(cabinet_id=cabinet_id, invoice_number__startswith=prefix)
            .aggregate(max_number=Max("invoice_number"))
            .get("max_number")
        )
        next_seq = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
        return f"{prefix}{next_seq:04d}"

    @property
    def subtotal(self):
        """Somme des lignes, avant remise."""
        return sum((item.price for item in self.items.all()), Decimal("0"))

    @property
    def amount_paid(self):
        # Parcourt les paiements préchargés (prefetch_related) plutôt qu'un aggregate par ligne.
        return sum((payment.amount for payment in self.payments.all()), Decimal("0"))

    @property
    def balance_due(self):
        if self.status == self.Status.CANCELLED:
            return Decimal("0")
        return max(self.total_amount - self.amount_paid, Decimal("0"))

    @property
    def is_cancelled(self):
        return self.status == self.Status.CANCELLED

    @property
    def is_locked(self):
        """Encaissée (même en partie) ou annulée : les montants ne bougent plus."""
        return self.is_cancelled or self.payments.exists()

    @property
    def status_tone(self):
        return {
            self.Status.PENDING: "amber",
            self.Status.PARTIAL: "sky",
            self.Status.PAID: "emerald",
        }.get(self.status, "slate")

    def refresh_payment_status(self):
        """Statut et dernier paiement recalculés depuis les Payment (hors facture annulée)."""
        if self.is_cancelled:
            return
        last = self.payments.order_by("-paid_at", "-pk").first()
        paid = self.amount_paid
        if self.total_amount <= paid and (paid > 0 or self.is_free):
            self.status = self.Status.PAID
        elif paid > 0:
            self.status = self.Status.PARTIAL
        else:
            self.status = self.Status.PENDING
        self.paid_at = last.paid_at if last else None
        self.payment_method = last.method if last else ""
        self.save(update_fields=["status", "paid_at", "payment_method"])


class Payment(models.Model):
    """Un encaissement (total ou partiel). Les recettes comptent à `paid_at`."""

    Method = PaymentMethod

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField("Mode", max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(
        "Référence", max_length=60, blank=True, help_text="N° de chèque ou de virement."
    )
    paid_at = models.DateTimeField(default=timezone.now)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ["paid_at", "pk"]

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.amount} ({self.get_method_display()})"

    @property
    def receipt_number(self):
        """N° du reçu : numéro de facture + rang du paiement (FAC-2026-0012-1)."""
        rank = self.invoice.payments.filter(
            models.Q(paid_at__lt=self.paid_at) | models.Q(paid_at=self.paid_at, pk__lte=self.pk)
        ).count()
        return f"{self.invoice.invoice_number}-{rank}"


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    act = models.ForeignKey(MedicalAct, on_delete=models.PROTECT, related_name="invoice_items")
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.act.name}"


class CashClosing(models.Model):
    """Clôture de caisse d'une journée : espèces comptées face aux espèces attendues."""

    cabinet = models.ForeignKey(Cabinet, on_delete=models.CASCADE, related_name="cash_closings")
    date = models.DateField("Journée")
    expected_cash = models.DecimalField("Espèces attendues", max_digits=10, decimal_places=2)
    counted_cash = models.DecimalField("Espèces comptées", max_digits=10, decimal_places=2)
    difference = models.DecimalField("Écart", max_digits=10, decimal_places=2)
    note = models.TextField("Commentaire", blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    closed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Clôture de caisse"
        verbose_name_plural = "Clôtures de caisse"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["cabinet", "date"], name="unique_cash_closing_per_day"),
        ]

    def __str__(self):
        return f"Clôture du {self.date:%d/%m/%Y}"
