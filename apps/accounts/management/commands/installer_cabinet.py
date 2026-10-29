"""Prépare le cabinet de Dr Errmili sur une base neuve (installation au cabinet).

    python manage.py installer_cabinet

Idempotent : relancée, la commande complète ce qui manque sans rien écraser
(ni les tarifs modifiés par la doctoresse, ni les mots de passe existants).
Les mots de passe sont demandés au clavier, jamais écrits dans un fichier.
"""
import getpass
from datetime import time
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Cabinet, PrintProfile, Profile
from apps.billing.models import MedicalAct
from apps.clinical.modeles_ordonnance_defaut import creer_modeles_defaut
from apps.clinical.courriers import creer_modeles_courrier_defaut
from apps.clinical.models import ModeleCourrier, ModeleOrdonnance

SLUG = "cabinet-dr-errmili"
CABINET = {
    "nom": "Cabinet Dr ERRMILI",
    "ville": "Khemisset",
    "couleur_primaire": "#B84A6E",
    "modes_paiement": ["cash"],
    "paiement_partiel": False,
    "heure_ouverture": time(9, 0),
    "heure_fermeture": time(17, 0),
    "heure_fermeture_samedi": time(13, 0),
    "dimanche_ferme": True,
    "controle_gratuit_jours": 20,
    "telephone_whatsapp": "06 66 54 69 54",
}
LOGO = Path(settings.BASE_DIR) / "static" / "images" / "logo-cabinet.jpg"

# code, libellé, prix, examen rapide, prix libre (réponses de Dr Errmili : consultation 300 DH, le reste à la main)
ACTS = [
    ("CONS_GYN", "Consultation gynécologique", "300", False, False),
    ("ECHO_OBST", "Échographie obstétricale", "0", False, True),
    ("ECHO_PELV", "Échographie pelvienne", "0", False, True),
    ("FROTTIS", "Frottis cervico-vaginal", "0", True, True),
    ("STERILET", "Pose stérilet", "0", False, True),
    ("PRELEV_BACT", "Prélèvement bactériologique", "0", True, True),
    ("POSE_SONDE", "Pose de sonde vésicale", "0", True, True),
]

# Papier pré-imprimé A5 pour tous les documents (réglé avec la doctoresse le 17/10/2026).
# Décalage vertical mesuré sur l'imprimante du cabinet : le texte sortait ~14 mm trop haut.
PRINT_FORMAT = "A5"
PRINT_OFFSET_Y_MM = Decimal("14")

ACCOUNTS = [
    ("dr_errmili", Profile.Role.DOCTOR, "Khadija", "Errmili", "la doctoresse"),
    ("assistante", Profile.Role.ASSISTANT, "", "", "l'assistante"),
]


class Command(BaseCommand):
    help = "Crée ou complète le cabinet Dr Errmili : réglages, logo, actes et comptes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sans-mots-de-passe", action="store_true",
            help="Ne pas demander les mots de passe (comptes déjà créés).",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            cabinet = self.setup_cabinet()
            self.setup_acts(cabinet)
            self.setup_print_profiles(cabinet)
            created = creer_modeles_defaut(cabinet, ModeleOrdonnance)
            if created:
                self.stdout.write(f"Modèles d'ordonnance : {created} ajouté(s).")
            created = creer_modeles_courrier_defaut(cabinet, ModeleCourrier)
            if created:
                self.stdout.write(f"Modèles de certificats et courriers : {created} ajouté(s).")
        for username, role, first_name, last_name, label in ACCOUNTS:
            self.setup_account(cabinet, username, role, first_name, last_name, label,
                               ask_password=not options["sans_mots_de_passe"])
        self.stdout.write(self.style.SUCCESS(
            f"\nCabinet prêt. Connexion : /c/{SLUG}/login/  (comptes : "
            + ", ".join(a[0] for a in ACCOUNTS) + ")"
        ))

    def setup_cabinet(self):
        cabinet, created = Cabinet.objects.get_or_create(slug=SLUG, defaults=CABINET)
        if created:
            self.stdout.write(f"Cabinet créé : {cabinet.nom}")
        else:
            self.stdout.write(f"Cabinet existant conservé : {cabinet.nom}")
        if not cabinet.logo and LOGO.exists():
            with LOGO.open("rb") as handle:
                cabinet.logo.save(LOGO.name, File(handle), save=True)
            self.stdout.write("Logo du cabinet ajouté.")
        return cabinet

    def setup_acts(self, cabinet):
        added = 0
        for code, name, price, quick, free in ACTS:
            _, created = MedicalAct.objects.get_or_create(
                cabinet=cabinet, code=code,
                defaults={"name": name, "price": Decimal(price), "is_quick_exam": quick, "prix_libre": free},
            )
            added += created
        self.stdout.write(f"Actes : {added} ajouté(s), {len(ACTS) - added} déjà présent(s).")

    def setup_print_profiles(self, cabinet):
        """A5 + décalage du cabinet ; un profil déjà ajusté à la main n'est jamais écrasé."""
        adjusted = 0
        for document_type in PrintProfile.DocumentType.values:
            profile, created = PrintProfile.objects.get_or_create(
                cabinet=cabinet, document_type=document_type,
                defaults={"format": PRINT_FORMAT, "decalage_y_mm": PRINT_OFFSET_Y_MM},
            )
            factory = profile.format == "A4" and not profile.decalage_x_mm and not profile.decalage_y_mm
            if created or factory:
                profile.format, profile.decalage_y_mm = PRINT_FORMAT, PRINT_OFFSET_Y_MM
                profile.save(update_fields=["format", "decalage_y_mm"])
                adjusted += 1
        self.stdout.write(f"Impression : {adjusted} document(s) réglé(s) en {PRINT_FORMAT}, décalage vertical {PRINT_OFFSET_Y_MM} mm.")

    def setup_account(self, cabinet, username, role, first_name, last_name, label, ask_password):
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": first_name, "last_name": last_name},
        )
        Profile.objects.update_or_create(user=user, defaults={"role": role, "cabinet": cabinet})
        if not created and user.has_usable_password():
            self.stdout.write(f"Compte {username} ({label}) déjà en place, mot de passe conservé.")
            return
        if not ask_password:
            user.set_unusable_password()
            user.save()
            self.stdout.write(self.style.WARNING(f"Compte {username} créé SANS mot de passe."))
            return
        user.set_password(self.ask_password(user, label))
        user.save()
        self.stdout.write(self.style.SUCCESS(f"Compte {username} ({label}) prêt."))

    def ask_password(self, user, label):
        while True:
            first = getpass.getpass(f"Mot de passe pour {user.username} ({label}) : ")
            if getpass.getpass("Retapez-le : ") != first:
                self.stdout.write(self.style.ERROR("Les deux saisies sont différentes, recommencez."))
                continue
            try:
                validate_password(first, user)
            except ValidationError as error:
                self.stdout.write(self.style.ERROR(" ".join(error.messages)))
                continue
            return first
