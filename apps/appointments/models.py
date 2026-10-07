from django.db import models
from django.utils import timezone

from apps.accounts.models import Cabinet
from apps.common.whatsapp import appointment_reminder_link
from apps.patients.models import Patient


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Planifié"
        ARRIVED = "arrived", "Arrivée"
        WAITING = "waiting", "En attente"
        IN_CONSULTATION = "in_consultation", "En consultation"
        COMPLETED = "completed", "Terminé"
        CANCELLED = "cancelled", "Annulé"

    class WhatsappStatus(models.TextChoices):
        PENDING = "pending", "En attente"
        SENT = "sent", "Envoyé"
        CONFIRMED = "confirmed", "Confirmé"
        RESCHEDULED = "rescheduled", "Reprogrammé"
        CANCELLED = "cancelled", "Annulé"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="appointments", null=True, blank=True
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="appointments"
    )
    date = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=30)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    reason = models.CharField(max_length=255, blank=True)
    whatsapp_status = models.CharField(
        max_length=20, choices=WhatsappStatus.choices, default=WhatsappStatus.PENDING
    )
    admin_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Rendez-vous"
        verbose_name_plural = "Rendez-vous"
        ordering = ["date"]

    def __str__(self):
        return f"{self.patient} — {self.date:%d/%m/%Y %H:%M}"

    @property
    def whatsapp_reminder_link(self):
        local_dt = timezone.localtime(self.date)
        return appointment_reminder_link(
            self.patient, local_dt.strftime("%d/%m/%Y"), local_dt.strftime("%H:%M")
        )
