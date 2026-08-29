from django.db import models
from django.db.models import Max
from django.utils import timezone

from apps.patients.models import Patient


class MedicalAct(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Acte médical"
        verbose_name_plural = "Actes médicaux"
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class Invoice(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        PAID = "paid", "Payée"
        CANCELLED = "cancelled", "Annulée"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Espèces"
        CARD = "card", "Carte"
        CHECK = "check", "Chèque"

    invoice_number = models.CharField(max_length=20, unique=True, editable=False)
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="invoices"
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    payment_method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, blank=True
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Facture"
        verbose_name_plural = "Factures"
        ordering = ["-created_at"]

    def __str__(self):
        return self.invoice_number

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._generate_invoice_number()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_invoice_number(cls):
        year = timezone.now().year
        prefix = f"FAC-{year}-"
        last = (
            cls.objects.filter(invoice_number__startswith=prefix)
            .aggregate(max_number=Max("invoice_number"))
            .get("max_number")
        )
        next_seq = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
        return f"{prefix}{next_seq:04d}"

    def recalculate_total(self, commit=True):
        total = self.items.aggregate(total=models.Sum("price"))["total"] or 0
        self.total_amount = total
        if commit:
            self.save(update_fields=["total_amount"])
        return total


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    act = models.ForeignKey(MedicalAct, on_delete=models.PROTECT, related_name="invoice_items")
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Ligne de facture"
        verbose_name_plural = "Lignes de facture"

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.act.name}"
