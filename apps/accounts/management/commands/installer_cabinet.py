"""Prépare un cabinet sur une base neuve, ou complète celui qui existe (installation et mises à jour).

    python manage.py installer_cabinet                    # complète le(s) cabinet(s) existant(s)
                                                          # ou, base vide : questions au clavier
    python manage.py installer_cabinet --preset errmili   # cabinet du Dr Errmili
    python manage.py installer_cabinet --nom "Cabinet Dr Alami" --ville Rabat \\
        --specialite generaliste --medecin-prenom Samir --medecin-nom Alami --tarif-consultation 250

Idempotent : relancée, la commande complète ce qui manque sans rien écraser (ni les tarifs,
ni un acte ou un modèle supprimé par le médecin, ni les mots de passe existants).
Les mots de passe sont demandés au clavier, jamais écrits dans un fichier.
"""
import getpass
import re
from datetime import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.accounts.models import Cabinet, PrintProfile, Profile
from apps.accounts.specialites import GYNECOLOGIE, SPECIALITE_CHOICES, SPECIALITE_LABELS, actes_de_depart
from apps.billing.models import MedicalAct
from apps.clinical.courriers import creer_modeles_courrier_defaut
from apps.clinical.modeles_ordonnance_defaut import creer_modeles_defaut
from apps.clinical.models import ModeleCourrier, ModeleOrdonnance

STATIC = Path(settings.BASE_DIR) / "static"

# Cabinet du Dr Errmili (gynécologie, Khemisset) : réglages validés avec elle le 17/10/2026.
ERRMILI = {
    "slug": "cabinet-dr-errmili",
    "cabinet": {
        "nom": "Cabinet Dr ERRMILI",
        "specialite": GYNECOLOGIE,
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
    },
    "logo": STATIC / "images" / "logo-cabinet.jpg",
    "entetes": {"entete_pdf": STATIC / "pdf" / "entete_cabinet.pdf",
                "entete_ordonnance_pdf": STATIC / "pdf" / "ordonnance_modele.pdf"},
    "tarif_consultation": Decimal("300"),
    # Papier pré-imprimé A5 ; décalage vertical mesuré sur l'imprimante du cabinet (~14 mm trop haut).
    "impression": ("A5", Decimal("14")),
    "comptes": [
        ("dr_errmili", Profile.Role.DOCTOR, "Khadija", "Errmili", "la doctoresse"),
        ("assistante", Profile.Role.ASSISTANT, "", "", "l'assistante"),
    ],
}
PRESETS = {"errmili": ERRMILI}


class Command(BaseCommand):
    help = "Crée un cabinet (préréglage, options ou questions) ou complète le(s) cabinet(s) existant(s)."

    def add_arguments(self, parser):
        parser.add_argument("--preset", choices=sorted(PRESETS), help="Cabinet préréglé (ex. errmili).")
        parser.add_argument("--nom", help="Nom du cabinet (ex. « Cabinet Dr Alami »).")
        parser.add_argument("--ville")
        parser.add_argument("--specialite", choices=[code for code, _ in SPECIALITE_CHOICES])
        parser.add_argument("--medecin-prenom")
        parser.add_argument("--medecin-nom")
        parser.add_argument("--identifiant-medecin", help="Identifiant de connexion du médecin (défaut : dr_<nom>).")
        parser.add_argument("--tarif-consultation", help="Prix de la consultation en DH.")
        parser.add_argument("--non-interactif", action="store_true", help="Ne jamais poser de question.")
        parser.add_argument(
            "--sans-mots-de-passe", action="store_true",
            help="Ne pas demander les mots de passe (comptes déjà créés).",
        )

    def handle(self, *args, **options):
        self.ask_passwords = not options["sans_mots_de_passe"]
        self.interactive = not options["non_interactif"]
        if options["preset"]:
            self.install_preset(PRESETS[options["preset"]])
        elif options["nom"]:
            self.install_new(self.config_from_options(options))
        elif Cabinet.objects.exists():
            for cabinet in Cabinet.objects.all():
                self.complete_existing(cabinet)
        elif self.interactive:
            self.install_new(self.config_from_questions())
        else:
            raise CommandError("Base vide : précisez --preset ou --nom (ou lancez sans --non-interactif).")

    # ── Trois façons d'arriver à un cabinet ─────────────────────────────────

    def install_preset(self, preset):
        with transaction.atomic():
            cabinet, created = Cabinet.objects.get_or_create(slug=preset["slug"], defaults=preset["cabinet"])
            self.report_cabinet(cabinet, created)
            self.attach_file(cabinet, "logo", preset.get("logo"), "Logo du cabinet ajouté.")
            for field, path in preset.get("entetes", {}).items():
                self.attach_file(cabinet, field, path, "Papier à en-tête du cabinet ajouté.")
            self.setup_acts(cabinet, preset["tarif_consultation"])
            self.setup_print_profiles(cabinet, *preset["impression"])
            self.setup_models(cabinet)
        for account in preset["comptes"]:
            self.setup_account(cabinet, *account)
        self.done(cabinet, [a[0] for a in preset["comptes"]])

    def install_new(self, config):
        with transaction.atomic():
            cabinet, created = Cabinet.objects.get_or_create(slug=config["slug"], defaults=config["cabinet"])
            self.report_cabinet(cabinet, created)
            self.setup_acts(cabinet, config["tarif_consultation"])
            PrintProfile.ensure_defaults(cabinet)
            self.setup_models(cabinet)
        accounts = [
            (config["identifiant_medecin"], Profile.Role.DOCTOR, config["prenom"], config["nom_medecin"], "le médecin"),
            (unique_username("assistante", cabinet), Profile.Role.ASSISTANT, "", "", "l'assistante"),
        ]
        if created:
            for account in accounts:
                self.setup_account(cabinet, *account)
        self.done(cabinet, [a[0] for a in accounts] if created else [])

    def complete_existing(self, cabinet):
        """Mise à jour : complète un cabinet existant sans rien écraser."""
        preset = next((p for p in PRESETS.values() if p["slug"] == cabinet.slug), None)
        if preset:
            self.install_preset(preset)
            return
        with transaction.atomic():
            self.report_cabinet(cabinet, False)
            PrintProfile.ensure_defaults(cabinet)
            self.setup_models(cabinet)
        self.stdout.write(self.style.SUCCESS(f"Cabinet à jour : {cabinet.nom}."))

    # ── Configuration ────────────────────────────────────────────────────────

    def config_from_options(self, options):
        if not options["medecin_nom"]:
            raise CommandError("--medecin-nom est obligatoire avec --nom.")
        return self.build_config(
            nom=options["nom"], ville=options["ville"] or "", specialite=options["specialite"] or GYNECOLOGIE,
            prenom=options["medecin_prenom"] or "", nom_medecin=options["medecin_nom"],
            identifiant=options["identifiant_medecin"], tarif=options["tarif_consultation"],
        )

    def config_from_questions(self):
        self.stdout.write("Base vide : création d'un nouveau cabinet.\n")
        nom = self.ask("Nom du cabinet (ex. Cabinet Dr Alami)", required=True)
        ville = self.ask("Ville")
        self.stdout.write("Spécialité :")
        for index, (_, label) in enumerate(SPECIALITE_CHOICES, start=1):
            self.stdout.write(f"  {index}. {label}")
        while True:
            choice = self.ask("Numéro de la spécialité", default="1")
            if choice.isdigit() and 1 <= int(choice) <= len(SPECIALITE_CHOICES):
                specialite = SPECIALITE_CHOICES[int(choice) - 1][0]
                break
            self.stdout.write(self.style.ERROR("Choix invalide."))
        prenom = self.ask("Prénom du médecin")
        nom_medecin = self.ask("Nom du médecin", required=True)
        identifiant = self.ask("Identifiant de connexion du médecin", default=default_doctor_username(nom_medecin))
        tarif = self.ask("Prix de la consultation (DH)", default="300")
        return self.build_config(nom=nom, ville=ville, specialite=specialite, prenom=prenom,
                                 nom_medecin=nom_medecin, identifiant=identifiant, tarif=tarif)

    def build_config(self, *, nom, ville, specialite, prenom, nom_medecin, identifiant, tarif):
        if specialite not in SPECIALITE_LABELS:
            raise CommandError(f"Spécialité inconnue : {specialite}.")
        try:
            tarif = Decimal(str(tarif or "0").replace(",", ".")).quantize(Decimal("0.01"))
        except InvalidOperation as error:
            raise CommandError("Prix de la consultation invalide.") from error
        identifiant = identifiant or default_doctor_username(nom_medecin)
        if not re.fullmatch(r"[\w.@+-]{3,150}", identifiant):
            raise CommandError("Identifiant du médecin invalide (lettres, chiffres, point ou tiret, sans espace).")
        return {
            "slug": slugify(nom) or "cabinet",
            "cabinet": {"nom": nom.strip()[:150], "ville": ville.strip()[:80], "specialite": specialite},
            "prenom": prenom.strip(), "nom_medecin": nom_medecin.strip(),
            "identifiant_medecin": identifiant, "tarif_consultation": tarif,
        }

    def ask(self, question, default="", required=False):
        while True:
            suffix = f" [{default}]" if default else ""
            answer = input(f"{question}{suffix} : ").strip() or default
            if answer or not required:
                return answer
            self.stdout.write(self.style.ERROR("Réponse obligatoire."))

    # ── Étapes ───────────────────────────────────────────────────────────────

    def report_cabinet(self, cabinet, created):
        if created:
            self.stdout.write(f"Cabinet créé : {cabinet.nom} ({cabinet.get_specialite_display()})")
        else:
            self.stdout.write(f"Cabinet existant conservé : {cabinet.nom}")

    def attach_file(self, cabinet, field, path, message):
        if path and not getattr(cabinet, field) and Path(path).exists():
            with Path(path).open("rb") as handle:
                getattr(cabinet, field).save(f"{cabinet.slug}_{Path(path).name}", File(handle), save=True)
            self.stdout.write(message)

    def setup_acts(self, cabinet, consultation_price):
        """Actes de départ de la spécialité, seulement pour un cabinet qui n'en a encore aucun."""
        if MedicalAct.objects.filter(cabinet=cabinet).exists():
            self.stdout.write(f"Actes : {MedicalAct.objects.filter(cabinet=cabinet).count()} déjà en place, conservés.")
            return
        acts = actes_de_depart(cabinet.specialite)
        for index, (code, name, quick, free) in enumerate(acts):
            price = consultation_price if index == 0 and not free else Decimal("0")
            MedicalAct.objects.create(cabinet=cabinet, code=code, name=name, price=price,
                                      is_quick_exam=quick, prix_libre=free)
        self.stdout.write(f"Actes : {len(acts)} ajouté(s).")

    def setup_print_profiles(self, cabinet, page_format, offset_y):
        """Format et décalage du cabinet ; un profil déjà ajusté à la main n'est jamais écrasé."""
        adjusted = 0
        for document_type in PrintProfile.DocumentType.values:
            profile, created = PrintProfile.objects.get_or_create(
                cabinet=cabinet, document_type=document_type,
                defaults={"format": page_format, "decalage_y_mm": offset_y},
            )
            factory = profile.format == "A4" and not profile.decalage_x_mm and not profile.decalage_y_mm
            if created or factory:
                profile.format, profile.decalage_y_mm = page_format, offset_y
                profile.save(update_fields=["format", "decalage_y_mm"])
                adjusted += 1
        self.stdout.write(f"Impression : {adjusted} document(s) réglé(s) en {page_format}, décalage vertical {offset_y} mm.")

    def setup_models(self, cabinet):
        created = creer_modeles_defaut(cabinet, ModeleOrdonnance, cabinet.specialite)
        if created:
            self.stdout.write(f"Modèles d'ordonnance : {created} ajouté(s).")
        created = creer_modeles_courrier_defaut(cabinet, ModeleCourrier, cabinet.specialite)
        if created:
            self.stdout.write(f"Modèles de certificats et courriers : {created} ajouté(s).")

    def setup_account(self, cabinet, username, role, first_name, last_name, label):
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": first_name, "last_name": last_name},
        )
        profile = getattr(user, "profile", None)
        if not created and profile is not None and profile.cabinet_id not in (None, cabinet.pk):
            raise CommandError(f"L'identifiant {username} appartient déjà à un autre cabinet.")
        Profile.objects.update_or_create(user=user, defaults={"role": role, "cabinet": cabinet})
        if not created and user.has_usable_password():
            self.stdout.write(f"Compte {username} ({label}) déjà en place, mot de passe conservé.")
            return
        if not self.ask_passwords:
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

    def done(self, cabinet, usernames):
        accounts = f"  (comptes : {', '.join(usernames)})" if usernames else ""
        self.stdout.write(self.style.SUCCESS(f"\nCabinet prêt. Connexion : /c/{cabinet.slug}/login/{accounts}"))


def default_doctor_username(last_name):
    return f"dr_{slugify(last_name).replace('-', '_')}" if last_name else "medecin"


def unique_username(base, cabinet):
    """`base` s'il est libre ou déjà rattaché à ce cabinet, sinon base_2, base_3…"""
    username, index = base, 2
    while True:
        user = User.objects.filter(username=username).select_related("profile").first()
        if user is None or getattr(getattr(user, "profile", None), "cabinet_id", None) == cabinet.pk:
            return username
        username, index = f"{base}_{index}", index + 1
