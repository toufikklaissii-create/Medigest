from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from apps.accounts.models import Cabinet

from .couverture import COUVERTURE_CHOICES, libelle


class Patient(models.Model):
    class BloodGroup(models.TextChoices):
        A_POS = "A+", "A+"
        A_NEG = "A-", "A-"
        B_POS = "B+", "B+"
        B_NEG = "B-", "B-"
        AB_POS = "AB+", "AB+"
        AB_NEG = "AB-", "AB-"
        O_POS = "O+", "O+"
        O_NEG = "O-", "O-"

    cabinet = models.ForeignKey(
        Cabinet, on_delete=models.CASCADE, related_name="patients", null=True, blank=True
    )
    patient_number = models.CharField(max_length=20, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    cin = models.CharField("CIN", max_length=20, blank=True)
    social_security_number = models.CharField(
        "N° de Sécurité Sociale", max_length=20, blank=True
    )
    couverture = models.CharField(
        "Couverture médicale", max_length=10, choices=COUVERTURE_CHOICES, blank=True,
        help_text="Vide = non renseignée (à vérifier).",
    )
    organisme_social = models.CharField(
        "Précision (mutuelle, n° d'affiliation…)", max_length=100, blank=True
    )
    birth_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    emergency_contact = models.CharField(max_length=150, blank=True)
    blood_group = models.CharField(
        max_length=3, choices=BloodGroup.choices, blank=True
    )
    allergies = models.TextField(blank=True)
    medical_history = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Patiente"
        verbose_name_plural = "Patientes"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cabinet", "patient_number"], name="unique_patient_number_per_cabinet"
            ),
        ]

    def __str__(self):
        return f"{self.patient_number} — {self.first_name} {self.last_name}"

    @property
    def couverture_label(self):
        return libelle(self.couverture)

    @property
    def full_name(self):
        """Prénom + nom, sans N° de dossier (toasts, micro-copie)."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def age(self):
        if not self.birth_date:
            return None
        today = timezone.now().date()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    def save(self, *args, **kwargs):
        if self.patient_number:
            super().save(*args, **kwargs)
            return
        # Number generation and INSERT share one transaction holding the cabinet
        # row lock, so two concurrent creations can't read the same Max().
        with transaction.atomic():
            self.patient_number = self._generate_patient_number(self.cabinet_id)
            super().save(*args, **kwargs)

    @classmethod
    def _generate_patient_number(cls, cabinet_id):
        """Next PAT-<year>-NNNN for this cabinet. Must run inside transaction.atomic()."""
        if cabinet_id is not None:
            Cabinet.objects.select_for_update().filter(pk=cabinet_id).first()
        year = timezone.now().year
        prefix = f"PAT-{year}-"
        last = (
            cls.objects.filter(cabinet_id=cabinet_id, patient_number__startswith=prefix)
            .aggregate(max_number=Max("patient_number"))
            .get("max_number")
        )
        next_seq = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
        return f"{prefix}{next_seq:04d}"
