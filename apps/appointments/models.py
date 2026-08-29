from django.db import models

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
