from django.conf import settings
from django.db import models

from apps.accounts.models import Cabinet
from apps.patients.models import Patient


class Task(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "À faire"
        IN_PROGRESS = "in_progress", "En cours"
        COMPLETED = "completed", "Terminée"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normale"
        URGENT = "urgent", "Urgente"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="tasks", null=True, blank=True
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="authored_tasks"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assigned_tasks"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tâche"
        verbose_name_plural = "Tâches"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
