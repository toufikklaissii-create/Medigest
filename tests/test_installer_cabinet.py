"""Installation au cabinet sur une base neuve : `manage.py installer_cabinet`."""

import io
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from apps.accounts.models import Cabinet
from apps.billing.models import MedicalAct

PASSWORD = "Khemisset-2026!"


class InstallerCabinetTest(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

    def run_command(self, *args, passwords=(PASSWORD,) * 4):
        out = io.StringIO()
        with mock.patch("getpass.getpass", side_effect=list(passwords)):
            call_command("installer_cabinet", *args, stdout=out)
        return out.getvalue()

    def test_fresh_database_gets_errmili_cabinet(self):
        self.run_command("--preset", "errmili")
        cabinet = Cabinet.objects.get(slug="cabinet-dr-errmili")
        self.assertEqual(cabinet.ville, "Khemisset")
        self.assertEqual(cabinet.couleur_primaire, "#B84A6E")
        self.assertTrue(cabinet.cash_only_simple)
        self.assertEqual(cabinet.telephone_whatsapp, "06 66 54 69 54")
        self.assertEqual(cabinet.controle_gratuit_jours, 20)
        self.assertTrue(cabinet.logo.name.startswith("cabinets/logos/"))

        consultation = MedicalAct.objects.get(cabinet=cabinet, code="CONS_GYN")
        self.assertEqual(consultation.price, Decimal("300"))
        self.assertFalse(consultation.prix_libre)
        self.assertEqual(MedicalAct.objects.filter(cabinet=cabinet, prix_libre=True).count(), 6)

        doctor = User.objects.get(username="dr_errmili")
        self.assertTrue(doctor.profile.is_doctor)
        self.assertEqual(doctor.get_full_name(), "Khadija Errmili")
        self.assertTrue(User.objects.get(username="assistante").profile.is_assistant)
        self.assertTrue(Client().login(username="dr_errmili", password=PASSWORD))
        self.assertTrue(Client().login(username="assistante", password=PASSWORD))

    def test_rerun_keeps_prices_and_passwords(self):
        self.run_command("--preset", "errmili")
        act = MedicalAct.objects.get(code="ECHO_OBST")
        act.price, act.prix_libre = Decimal("450"), False
        act.save()
        # Mise à jour au cabinet : INSTALLER relance la commande sans option.
        output = self.run_command(passwords=())  # aucun mot de passe redemandé
        act.refresh_from_db()
        self.assertEqual((act.price, act.prix_libre), (Decimal("450"), False))
        self.assertIn("mot de passe conservé", output)
        self.assertEqual(Cabinet.objects.count(), 1)
        self.assertTrue(Client().login(username="dr_errmili", password=PASSWORD))

    def test_mismatch_and_weak_password_are_asked_again(self):
        self.run_command("--preset", "errmili",
                         passwords=(PASSWORD, "autre", "123", "123", PASSWORD, PASSWORD, PASSWORD, PASSWORD))
        self.assertTrue(Client().login(username="dr_errmili", password=PASSWORD))

    def test_errmili_gets_her_own_letterhead(self):
        self.run_command("--preset", "errmili")
        cabinet = Cabinet.objects.get(slug="cabinet-dr-errmili")
        self.assertEqual(cabinet.specialite, "gynecologie")
        self.assertTrue(cabinet.entete_pdf.name.startswith("cabinets/entetes/"))
        self.assertTrue(cabinet.entete_ordonnance_pdf.name.startswith("cabinets/entetes/"))

    def test_new_cabinet_from_options(self):
        self.run_command("--nom", "Cabinet Dr Alami", "--ville", "Rabat", "--specialite", "generaliste",
                         "--medecin-prenom", "Samir", "--medecin-nom", "Alami", "--tarif-consultation", "250")
        cabinet = Cabinet.objects.get(slug="cabinet-dr-alami")
        self.assertEqual((cabinet.nom, cabinet.ville, cabinet.specialite), ("Cabinet Dr Alami", "Rabat", "generaliste"))
        self.assertFalse(cabinet.entete_pdf)  # en-tête généré, pas celui du Dr Errmili
        consultation = MedicalAct.objects.get(cabinet=cabinet, code="CONS")
        self.assertEqual(consultation.price, Decimal("250"))
        self.assertFalse(MedicalAct.objects.filter(cabinet=cabinet, code="CONS_GYN").exists())
        doctor = User.objects.get(username="dr_alami")
        self.assertTrue(doctor.profile.is_doctor)
        self.assertEqual(doctor.profile.cabinet, cabinet)
        self.assertEqual(User.objects.get(username="assistante").profile.cabinet, cabinet)
        # Hors gynécologie : pas de modèles de grossesse, pas de modèles d'ordonnance gynéco.
        from apps.clinical.models import ModeleCourrier, ModeleOrdonnance
        noms = set(ModeleCourrier.objects.filter(cabinet=cabinet).values_list("nom", flat=True))
        self.assertIn("Certificat médical simple", noms)
        self.assertNotIn("Déclaration de grossesse", noms)
        self.assertFalse(ModeleOrdonnance.objects.filter(cabinet=cabinet).exists())

    def test_new_cabinet_from_questions(self):
        answers = ["Cabinet Dr Benani", "Fès", "3", "Leila", "Benani", "", "200"]
        with mock.patch("builtins.input", side_effect=answers):
            self.run_command()
        cabinet = Cabinet.objects.get(slug="cabinet-dr-benani")
        self.assertEqual((cabinet.ville, cabinet.specialite), ("Fès", "pediatrie"))
        self.assertEqual(MedicalAct.objects.get(cabinet=cabinet, code="CONS_PED").price, Decimal("200"))
        self.assertTrue(User.objects.get(username="dr_benani").profile.is_doctor)

    def test_second_cabinet_does_not_steal_accounts(self):
        self.run_command("--preset", "errmili")
        self.run_command("--nom", "Cabinet Dr Alami", "--medecin-nom", "Alami")
        assistants = User.objects.filter(profile__role="assistant").order_by("username")
        self.assertEqual([u.username for u in assistants], ["assistante", "assistante_2"])
        self.assertEqual(User.objects.get(username="assistante").profile.cabinet.slug, "cabinet-dr-errmili")

    def test_update_never_readds_a_deleted_act(self):
        self.run_command("--preset", "errmili")
        MedicalAct.objects.filter(code="POSE_SONDE").delete()
        self.run_command(passwords=())
        self.assertFalse(MedicalAct.objects.filter(code="POSE_SONDE").exists())

    def test_empty_base_non_interactive_explains(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_command("--non-interactif")
