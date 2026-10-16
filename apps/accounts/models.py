from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from .branding import DEFAULT_PRIMARY


class Cabinet(models.Model):
    nom = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    initiales_logo = models.CharField(max_length=4, blank=True)
    logo = models.ImageField(upload_to="cabinets/logos/", blank=True)
    couleur_primaire = models.CharField(
        "Couleur primaire",
        max_length=7,
        default=DEFAULT_PRIMARY,
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Format attendu : #RRGGBB.")],
        help_text="Couleur de marque (pas 500) : toute la palette de l'interface en est dérivée.",
    )
    ville = models.CharField(
        "Ville", max_length=80, blank=True,
        help_text="Imprimée sur les documents : « Khemisset, le 16 octobre 2026 ».",
    )
    # Mentions légales des factures : imprimées seulement si renseignées.
    inpe = models.CharField("INPE", max_length=30, blank=True)
    identifiant_fiscal = models.CharField("Identifiant fiscal (IF)", max_length=30, blank=True)
    ice = models.CharField("ICE", max_length=30, blank=True)
    patente = models.CharField("Patente", max_length=30, blank=True)
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


class PrintProfile(models.Model):
    """Réglage d'impression d'un type de document sur le papier pré-imprimé du cabinet.

    Le décalage (mm) corrige l'écart propre à chaque imprimante : X positif vers la droite,
    Y positif vers le bas.
    """

    class DocumentType(models.TextChoices):
        ORDONNANCE = "ordonnance", "Ordonnance"
        COMPTE_RENDU = "compte_rendu", "Compte rendu"
        LETTRE = "lettre", "Lettres et certificats"
        FACTURE = "facture", "Facture"
        RECU = "recu", "Reçu"

    class Format(models.TextChoices):
        A4 = "A4", "A4"
        A5 = "A5", "A5"

    cabinet = models.ForeignKey(Cabinet, on_delete=models.CASCADE, related_name="print_profiles")
    document_type = models.CharField("Document", max_length=20, choices=DocumentType.choices)
    format = models.CharField(max_length=2, choices=Format.choices, default=Format.A4)
    decalage_x_mm = models.DecimalField("Décalage horizontal (mm)", max_digits=4, decimal_places=1, default=0)
    decalage_y_mm = models.DecimalField("Décalage vertical (mm)", max_digits=4, decimal_places=1, default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Profil d'impression"
        verbose_name_plural = "Profils d'impression"
        constraints = [
            models.UniqueConstraint(fields=["cabinet", "document_type"], name="unique_print_profile_per_type"),
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} ({self.format})"

    @classmethod
    def for_document(cls, cabinet, document_type):
        """Profil actif du cabinet, sinon A4 sans décalage (jamais enregistré)."""
        profile = None
        if cabinet is not None:
            profile = cls.objects.filter(cabinet=cabinet, document_type=document_type, actif=True).first()
        return profile or cls(cabinet=cabinet, document_type=document_type)

    @classmethod
    def ensure_defaults(cls, cabinet):
        """Les 5 profils du cabinet (créés en A4, décalage 0, s'ils manquent), dans l'ordre des types."""
        existing = {p.document_type: p for p in cls.objects.filter(cabinet=cabinet)}
        for value in cls.DocumentType.values:
            if value not in existing:
                existing[value] = cls.objects.create(cabinet=cabinet, document_type=value)
        return [existing[value] for value in cls.DocumentType.values]
