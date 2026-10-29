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
        self.run_command()
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
        self.run_command()
        act = MedicalAct.objects.get(code="ECHO_OBST")
        act.price, act.prix_libre = Decimal("450"), False
        act.save()
        output = self.run_command(passwords=())  # aucun mot de passe redemandé
        act.refresh_from_db()
        self.assertEqual((act.price, act.prix_libre), (Decimal("450"), False))
        self.assertIn("mot de passe conservé", output)
        self.assertEqual(Cabinet.objects.count(), 1)
        self.assertTrue(Client().login(username="dr_errmili", password=PASSWORD))

    def test_mismatch_and_weak_password_are_asked_again(self):
        self.run_command(passwords=(PASSWORD, "autre", "123", "123", PASSWORD, PASSWORD, PASSWORD, PASSWORD))
        self.assertTrue(Client().login(username="dr_errmili", password=PASSWORD))
