from django.conf import settings
from django.db import models


class Cabinet(models.Model):
    nom = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    initiales_logo = models.CharField(max_length=4, blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cabinet"
        verbose_name_plural = "Cabinets"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class Profile(models.Model):
    class Role(models.TextChoices):
        DOCTOR = "doctor", "Médecin"
        ASSISTANT = "assistant", "Assistante"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="profiles", null=True, blank=True
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ASSISTANT)

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profils"

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_role_display()})"

    @property
    def is_doctor(self):
        return self.role == self.Role.DOCTOR

    @property
    def is_assistant(self):
        return self.role == self.Role.ASSISTANT
