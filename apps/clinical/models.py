import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db import models

from apps.accounts.models import Cabinet
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, InvoiceItem, MedicalAct
from apps.patients.models import Patient


GESTATION_DAYS = 280


def pregnancy_dates(lmp, on_date):
    """Depuis la DDR : {"weeks", "days", "due_date"} au `on_date`, ou None hors grossesse plausible."""
    if not lmp or not on_date:
        return None
    elapsed = (on_date - lmp).days
    if elapsed < 0 or elapsed > GESTATION_DAYS + 21:
        return None
    return {
        "weeks": elapsed // 7,
        "days": elapsed % 7,
        "due_date": lmp + timedelta(days=GESTATION_DAYS),
    }


class Consultation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Brouillon"
        VALIDATED = "validated", "Validée"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="consultations", null=True, blank=True
    )
    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE, related_name="consultation"
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="consultations"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consultations"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    blood_pressure = models.CharField("Tension", max_length=20, blank=True)
    weight_kg = models.DecimalField(
        "Poids (kg)", max_digits=5, decimal_places=2, null=True, blank=True
    )
    height_cm = models.DecimalField(
        "Taille (cm)", max_digits=5, decimal_places=1, null=True, blank=True
    )
    clinical_exam = models.TextField("Examen clinique", blank=True)
    clinical_notes = models.TextField(blank=True)
    diagnostic = models.TextField(blank=True)
    last_menstrual_period = models.DateField(null=True, blank=True)
    gestational_age_weeks = models.IntegerField(null=True, blank=True)
    ultrasound_notes = models.TextField(blank=True)
    acts = models.ManyToManyField(
        MedicalAct, through="ConsultationAct", related_name="consultations"
    )
    invoice = models.OneToOneField(
        Invoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="consultation"
    )
    # Montants fixés par la doctoresse (onglet facturation), appliqués par _bill() à la validation.
    billing_discount = models.DecimalField("Remise (DH)", max_digits=10, decimal_places=2, default=0)
    billing_free = models.BooleanField("Gratuit / contrôle", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Consultation"
        verbose_name_plural = "Consultations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consultation {self.patient} — {self.created_at:%d/%m/%Y}"

    @property
    def bmi(self):
        """IMC = poids (kg) / taille (m)², arrondi à 0,1 — None si une mesure manque."""
        if not self.weight_kg or not self.height_cm:
            return None
        height_m = Decimal(self.height_cm) / 100
        return round(Decimal(self.weight_kg) / (height_m * height_m), 1)

    @property
    def is_validated(self):
        return self.status == self.Status.VALIDATED

    @property
    def pregnancy(self):
        """Terme (SA + jours) au jour du RDV et date prévue d'accouchement (DDR + 280 j)."""
        from django.utils import timezone

        reference = timezone.localtime(self.appointment.date).date() if self.appointment_id else None
        return pregnancy_dates(self.last_menstrual_period, reference)

    def save(self, *args, **kwargs):
        old_status = None
        if self.pk:
            old_status = (
                Consultation.objects.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
        super().save(*args, **kwargs)
        if old_status != self.Status.VALIDATED and self.status == self.Status.VALIDATED:
            self._bill()

    @property
    def billing_subtotal(self):
        return sum((line.price for line in self.consultation_acts.all()), Decimal("0"))

    @property
    def billing_total(self):
        """Net à payer : lignes − remise (bornée au sous-total), 0 si gratuit / contrôle."""
        if self.billing_free:
            return Decimal("0")
        subtotal = self.billing_subtotal
        return subtotal - min(self.billing_discount or 0, subtotal)

    def _bill(self):
        """Recopie lignes, remise et gratuité sur la facture liée, créée au besoin.

        Une facture encaissée (même en partie) est une pièce comptable : jamais réécrite.
        Une facture annulée garde son numéro ; la revalidation en émet une nouvelle.
        """
        invoice = self.invoice if self.invoice_id else None
        settled = invoice and invoice.status == Invoice.Status.PAID and not invoice.is_free
        if invoice and (settled or invoice.payments.exists()):
            return
        if invoice is None or invoice.is_cancelled:
            invoice = Invoice.objects.create(
                cabinet=self.cabinet, patient=self.patient, status=Invoice.Status.PENDING
            )
            Consultation.objects.filter(pk=self.pk).update(invoice=invoice)
            self.invoice = invoice

        invoice.items.all().delete()
        lines = list(self.consultation_acts.select_related("act"))
        InvoiceItem.objects.bulk_create(
            InvoiceItem(invoice=invoice, act=line.act, price=line.price) for line in lines
        )
        subtotal = sum((line.price for line in lines), Decimal("0"))
        invoice.discount = min(self.billing_discount or 0, subtotal)
        invoice.is_free = self.billing_free
        invoice.total_amount = Decimal("0") if self.billing_free else subtotal - invoice.discount
        invoice.save(update_fields=["total_amount", "discount", "is_free"])
        invoice.refresh_payment_status()


class ConsultationAct(models.Model):
    consultation = models.ForeignKey(
        Consultation, on_delete=models.CASCADE, related_name="consultation_acts"
    )
    act = models.ForeignKey(MedicalAct, on_delete=models.PROTECT, related_name="consultation_acts")
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Acte de consultation"
        verbose_name_plural = "Actes de consultation"

    def __str__(self):
        return f"{self.consultation} — {self.act.name}"


class Document(models.Model):
    class DocumentType(models.TextChoices):
        PRESCRIPTION = "prescription", "Ordonnance"
        REPORT = "report", "Compte-rendu"
        LETTER = "letter", "Lettre à un confrère"
        CERTIFICATE = "certificate", "Certificat de prise en charge"
        PREANESTHESIA = "preanesthesia", "Consultation pré-anesthésie"

    consultation = models.ForeignKey(
        Consultation, on_delete=models.CASCADE, related_name="documents"
    )
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    content = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_document_type_display()} — {self.consultation}"


def patient_document_path(instance, filename):
    """Rangement par patiente, nom aléatoire : le nom d'origine ne vit qu'en base (`original_name`)."""
    extension = Path(filename).suffix.lower()[:10]
    return f"patient_documents/{instance.cabinet_id or 0}/{instance.patient_id}/{uuid.uuid4().hex}{extension}"


class PatientDocument(models.Model):
    class DocumentType(models.TextChoices):
        RADIO = "radio", "Radio"
        ECHOGRAPHIE = "echographie", "Échographie"
        BILAN = "bilan", "Bilan biologique"
        COMPTE_RENDU = "compte_rendu", "Compte rendu externe"
        AUTRE = "autre", "Autre"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="patient_documents", null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="documents_joints"
    )
    consultation = models.ForeignKey(
        Consultation, on_delete=models.SET_NULL, related_name="patient_documents", null=True, blank=True
    )
    title = models.CharField(max_length=150)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.AUTRE)
    exam_date = models.DateField("Date de l'examen", null=True, blank=True)
    file = models.FileField(upload_to=patient_document_path, max_length=255)
    original_name = models.CharField("Nom d'origine", max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Document patiente"
        verbose_name_plural = "Documents patiente"
        ordering = [models.F("exam_date").desc(nulls_last=True), "-created_at"]

    def __str__(self):
        return f"{self.title} — {self.patient}"

    @property
    def is_image(self):
        return self.content_type in ("image/jpeg", "image/png")

    @property
    def is_pdf(self):
        return self.content_type == "application/pdf"
