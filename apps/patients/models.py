from django.db import models
from django.db.models import Max
from django.utils import timezone


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

    patient_number = models.CharField(max_length=20, unique=True, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    cin = models.CharField("CIN", max_length=20, blank=True)
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

    def __str__(self):
        return f"{self.patient_number} — {self.first_name} {self.last_name}"

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
        if not self.patient_number:
            self.patient_number = self._generate_patient_number()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_patient_number(cls):
        year = timezone.now().year
        prefix = f"PAT-{year}-"
        last = (
            cls.objects.filter(patient_number__startswith=prefix)
            .aggregate(max_number=Max("patient_number"))
            .get("max_number")
        )
        next_seq = int(last.rsplit("-", 1)[-1]) + 1 if last else 1
        return f"{prefix}{next_seq:04d}"
