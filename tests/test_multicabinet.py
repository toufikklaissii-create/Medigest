"""Lot 1 multi-cabinet : textes propres à chaque cabinet, spécialité, papier à en-tête par cabinet."""
import io
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation, Document
from apps.clinical.services import generate_letter_pdf, generate_prescription_pdf
from apps.common.letterhead import generated_letterhead, letterhead_for
from apps.patients.models import Patient
from tests.helpers import STATIC_PDF, attach_errmili_letterhead


def pdf_text(data):
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


@override_settings(ALLOWED_HOSTS=["testserver"])
class MultiCabinetBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.cabinet = Cabinet.objects.create(
            nom="Cabinet Dr Alami", slug="cabinet-alami", specialite="pediatrie", ville="Rabat",
            adresse="12 rue des Orangers", telephone="05 37 00 00 00", inpe="INPE-123",
        )
        self.doctor = User.objects.create_user(username="dr_alami", password="x", first_name="Samir", last_name="Alami")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.client = Client()
        self.client.force_login(self.doctor)


class TextesDuCabinetTest(MultiCabinetBase):
    def test_accueil_titre_et_specialite_du_cabinet(self):
        html = self.client.get(reverse("clinical:doctor_dashboard")).content.decode()
        self.assertIn("Bonjour, Dr ALAMI", html)
        self.assertIn("Cabinet Dr Alami", html)
        self.assertIn("Pédiatrie", html)
        for errmili in ("ERRMILI", "Errmili", "Gynécologie &amp; Obstétrique"):
            self.assertNotIn(errmili, html)

    def test_reglages_specialite_adresse_telephone(self):
        self.client.post(reverse("accounts:settings"), {
            "ville": "Salé", "inpe": "", "ice": "", "specialite": "generaliste",
            "adresse": "3 avenue Hassan II", "telephone": "05 37 11 11 11",
        })
        self.cabinet.refresh_from_db()
        self.assertEqual((self.cabinet.specialite, self.cabinet.adresse, self.cabinet.telephone, self.cabinet.ville),
                         ("generaliste", "3 avenue Hassan II", "05 37 11 11 11", "Salé"))


class EnteteGenereTest(MultiCabinetBase):
    def test_sans_papier_charge_entete_genere_avec_les_infos_du_cabinet(self):
        background = letterhead_for(self.cabinet)
        self.assertIsInstance(background, bytes)
        text = pdf_text(background)
        for expected in ("Cabinet Dr Alami", "Dr Samir Alami", "Pédiatrie", "12 rue des Orangers", "Rabat",
                         "05 37 00 00 00", "INPE INPE-123"):
            self.assertIn(expected, text)

    def test_entete_ordonnance_genere_avec_titre_et_ville(self):
        text = pdf_text(generated_letterhead(self.cabinet, ordonnance=True))
        self.assertIn("ORDONNANCE", text)
        self.assertIn("Rabat, le", text)

    def test_documents_d_un_cabinet_sans_papier_n_ont_jamais_l_entete_errmili(self):
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="Yasmine", last_name="Fictive")
        appt = Appointment.objects.create(cabinet=self.cabinet, patient=patient, date=timezone.now())
        consultation = Consultation.objects.create(appointment=appt, patient=patient, cabinet=self.cabinet,
                                                   doctor=self.doctor)
        for pdf in (generate_letter_pdf(consultation, "certificate", "Texte", save_copy=False),
                    generate_prescription_pdf(consultation, "Doliprane", save_copy=False)):
            text = pdf_text(pdf)
            self.assertIn("Cabinet Dr Alami", text)
            self.assertNotIn("Khemisset", text)
            self.assertNotIn("Errmili", text)
            self.assertEqual(len(PdfReader(io.BytesIO(pdf)).pages), 1)

    def test_papier_charge_prioritaire(self):
        attach_errmili_letterhead(self.cabinet)
        self.assertTrue(str(letterhead_for(self.cabinet)).endswith(".pdf"))
        self.assertIn("ordonnance_modele", str(letterhead_for(self.cabinet, ordonnance=True)))


class ChargementEnteteTest(MultiCabinetBase):
    def upload(self, name="entete.pdf", content=None):
        content = content if content is not None else (STATIC_PDF / "entete_cabinet.pdf").read_bytes()
        return SimpleUploadedFile(name, content, content_type="application/pdf")

    def test_chargement_puis_retrait(self):
        response = self.client.post(reverse("accounts:cabinet_letterhead"), {"entete_pdf": self.upload()})
        self.assertEqual(response.status_code, 302)
        self.cabinet.refresh_from_db()
        self.assertTrue(self.cabinet.entete_pdf.name.startswith("cabinets/entetes/"))
        self.client.post(reverse("accounts:cabinet_letterhead"), {"entete_pdf-supprimer": "1"})
        self.cabinet.refresh_from_db()
        self.assertFalse(self.cabinet.entete_pdf)

    def test_fichier_non_pdf_refuse(self):
        self.client.post(reverse("accounts:cabinet_letterhead"),
                         {"entete_pdf": self.upload("photo.pdf", b"GIF89a pas un pdf")})
        self.cabinet.refresh_from_db()
        self.assertFalse(self.cabinet.entete_pdf)

    def test_apercus(self):
        for kind in ("certificat", "ordonnance"):
            response = self.client.get(reverse("accounts:letterhead_preview", args=[kind]))
            self.assertEqual(response.status_code, 200)
            self.assertIn("Cabinet Dr Alami", pdf_text(response.content))
        self.assertEqual(self.client.get(reverse("accounts:letterhead_preview", args=["autre"])).status_code, 404)

    def test_reserve_a_la_doctoresse(self):
        assistant = User.objects.create_user(username="as_alami", password="x")
        Profile.objects.update_or_create(user=assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        client = Client()
        client.force_login(assistant)
        self.assertEqual(client.post(reverse("accounts:cabinet_letterhead"), {"entete_pdf": self.upload()}).status_code, 403)
        self.assertEqual(client.get(reverse("accounts:letterhead_preview", args=["certificat"])).status_code, 403)

    def test_page_reglages_propose_le_chargement(self):
        html = self.client.get(reverse("accounts:settings")).content.decode()
        self.assertIn(reverse("accounts:cabinet_letterhead"), html)
        self.assertIn('name="entete_pdf"', html)
        self.assertIn('name="specialite"', html)
