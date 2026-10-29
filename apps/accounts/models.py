from datetime import time

from django.conf import settings
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models

from .branding import DEFAULT_PRIMARY

# Valeurs de billing.models.PaymentMethod (pas d'import : billing dépend d'accounts).
PAYMENT_METHOD_VALUES = ["cash", "card", "check", "transfer"]


def all_payment_methods():
    return list(PAYMENT_METHOD_VALUES)


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
    # Encaissement : modes proposés à l'accueil et paiement partiel.
    modes_paiement = models.JSONField("Modes de paiement", default=all_payment_methods)
    paiement_partiel = models.BooleanField("Paiement partiel autorisé", default=True)
    # Horaires : bornes du planning jour, avertissement pour un RDV hors plage.
    heure_ouverture = models.TimeField("Ouverture", default=time(9, 0))
    heure_fermeture = models.TimeField("Fermeture", default=time(17, 0))
    heure_fermeture_samedi = models.TimeField("Fermeture le samedi", default=time(13, 0))
    dimanche_ferme = models.BooleanField("Fermé le dimanche", default=True)
    controle_gratuit_jours = models.PositiveSmallIntegerField(
        "Contrôle gratuit (jours)", default=20, validators=[MaxValueValidator(365)],
        help_text="Délai après une consultation facturée pendant lequel le contrôle est proposé gratuit.",
    )
    telephone_whatsapp = models.CharField(
        "Téléphone (WhatsApp)", max_length=30, blank=True,
        help_text="Ajouté à la fin des messages de rappel : « Pour toute question : … ».",
    )
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Cabinet"
        verbose_name_plural = "Cabinets"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    @property
    def payment_methods(self):
        """Modes activés, dans l'ordre canonique ; espèces si la liste est vide ou invalide."""
        enabled = [m for m in PAYMENT_METHOD_VALUES if m in (self.modes_paiement or [])]
        return enabled or ["cash"]

    @property
    def cash_only_simple(self):
        """Un seul mode et pas de partiel : encaissement en un clic."""
        return len(self.payment_methods) == 1 and not self.paiement_partiel

    def closing_time(self, day):
        """Heure de fermeture du jour, ou None si le cabinet est fermé ce jour-là."""
        if day.weekday() == 6 and self.dimanche_ferme:
            return None
        return self.heure_fermeture_samedi if day.weekday() == 5 else self.heure_fermeture

    def is_open_at(self, moment):
        """Le RDV (datetime local) tombe-t-il dans les horaires d'ouverture ?"""
        closing = self.closing_time(moment.date())
        return closing is not None and self.heure_ouverture <= moment.time() < closing


class Profile(models.Model):
    class Role(models.TextChoices):
        DOCTOR = "doctor", "Médecin"
        ASSISTANT = "assistant", "Assistante"
        # Remplace la doctoresse : tout le clinique, rien de ce qui touche à l'argent.
        REMPLACANT = "remplacant", "Médecin remplaçant"

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

    @property
    def is_remplacant(self):
        return self.role == self.Role.REMPLACANT

    @property
    def is_clinician(self):
        """Doctoresse ou remplaçant : accès au dossier médical et aux consultations."""
        return self.role in CLINICIAN_ROLES

    @property
    def sees_money(self):
        """Facturation, caisse, recettes, montants : tout le monde sauf le remplaçant."""
        return self.role != self.Role.REMPLACANT


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


# Rôles qui consultent (accès clinique). Le remplaçant n'a jamais accès à l'argent.
CLINICIAN_ROLES = (Profile.Role.DOCTOR, Profile.Role.REMPLACANT)
