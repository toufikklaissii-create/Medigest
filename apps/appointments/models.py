from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Cabinet
from apps.common import whatsapp
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
    whatsapp_sent_at = models.DateTimeField(null=True, blank=True)
    whatsapp_sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
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
    def local_date(self):
        return timezone.localtime(self.date)

    @property
    def whatsapp_phone_state(self):
        """"ok", "missing" (aucun numéro) ou "invalid" (numéro à vérifier)."""
        raw = self.patient.phone
        if not (raw or "").strip():
            return "missing"
        return "ok" if whatsapp.whatsapp_phone(raw) else "invalid"

    def _link(self, message):
        return whatsapp.whatsapp_link(self.patient.phone, message)

    @property
    def whatsapp_reminder_link(self):
        return self._link(whatsapp.reminder_message(self.patient.first_name, self.cabinet, self.local_date))

    @property
    def whatsapp_confirmation_link(self):
        return self._link(whatsapp.confirmation_message(self.patient.first_name, self.cabinet, self.local_date))

    @property
    def whatsapp_rescheduled_link(self):
        return self._link(whatsapp.rescheduled_message(self.patient.first_name, self.cabinet, self.local_date))

    @property
    def whatsapp_sent_label(self):
        """Ex : « Envoyé à 14h32 par Sara » (avec la date si l'envoi n'est pas d'aujourd'hui)."""
        if not self.whatsapp_sent_at:
            return ""
        sent = timezone.localtime(self.whatsapp_sent_at)
        when = f"{sent.hour}h{sent.minute:02d}"
        if sent.date() == timezone.localdate():
            label = f"Envoyé à {when}"
        else:
            label = f"Envoyé le {whatsapp.format_rdv_datetime(sent)}"
        user = self.whatsapp_sent_by
        if user:
            label += f" par {user.first_name or user.username}"
        return label

    def mark_whatsapp_sent(self, user):
        self.whatsapp_status = self.WhatsappStatus.SENT
        self.whatsapp_sent_at = timezone.now()
        self.whatsapp_sent_by = user
        self.save(update_fields=["whatsapp_status", "whatsapp_sent_at", "whatsapp_sent_by"])
