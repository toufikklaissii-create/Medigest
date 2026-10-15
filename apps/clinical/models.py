from django.conf import settings
from django.db import models
from django.db.models import Sum

from apps.accounts.models import Cabinet
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, InvoiceItem, MedicalAct
from apps.patients.models import Patient


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Consultation"
        verbose_name_plural = "Consultations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Consultation {self.patient} — {self.created_at:%d/%m/%Y}"

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

    def _bill(self):
        """Sum ConsultationAct prices into the linked Invoice (pending), creating it if needed."""
        if self.invoice_id and self.invoice.status == Invoice.Status.PAID:
            # Already cashed in: the invoice is an accounting record, never rewrite it.
            return
        if self.invoice_id:
            invoice = self.invoice
        else:
            invoice = Invoice.objects.create(
                cabinet=self.cabinet, patient=self.patient, status=Invoice.Status.PENDING
            )
            Consultation.objects.filter(pk=self.pk).update(invoice=invoice)
            self.invoice = invoice

        invoice.items.all().delete()
        for consultation_act in self.consultation_acts.select_related("act"):
            InvoiceItem.objects.create(
                invoice=invoice, act=consultation_act.act, price=consultation_act.price
            )
        total = invoice.items.aggregate(total=Sum("price"))["total"] or 0
        invoice.total_amount = total
        invoice.status = Invoice.Status.PENDING
        invoice.save(update_fields=["total_amount", "status"])


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


class PatientDocument(models.Model):
    class DocumentType(models.TextChoices):
        RADIO = "radio", "Radio"
        BILAN = "bilan", "Bilan"
        AUTRE = "autre", "Autre"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="patient_documents", null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="documents_joints"
    )
    title = models.CharField(max_length=150)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices, default=DocumentType.AUTRE)
    file = models.FileField(upload_to="patient_documents/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Document patiente"
        verbose_name_plural = "Documents patiente"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} — {self.patient}"
