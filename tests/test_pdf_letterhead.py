"""Tous les documents imprimés portent le papier à en-tête du cabinet (logo, coordonnées réelles)."""

import io
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, InvoiceItem, MedicalAct
from apps.billing.services import generate_receipt_pdf, record_payment
from apps.clinical import services
from apps.clinical.models import Consultation, ConsultationAct
from apps.patients.models import Patient

LETTERHEAD_MARKERS = ("Khadija Errmili", "Khemisset (en face de la Place El Massira)")
FAKE_HEADER = "Avenue Hassan II"


def pdf_pages(pdf_bytes):
    return [page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages]


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class LetterheadPdfTest(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test", ville="Khemisset")
        self.doctor = User.objects.create_user(username="dr_pdf", password="x", first_name="Khadija", last_name="Errmili")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Bennani", birth_date=date(1994, 3, 12),
        )
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(), reason="Suivi grossesse",
        )
        self.consultation = Consultation.objects.create(
            appointment=self.appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            blood_pressure="11/7", weight_kg=Decimal("68.5"), height_cm=Decimal("164"),
            last_menstrual_period=timezone.localdate() - timedelta(days=140),
            clinical_exam="Utérus souple, col fermé.", ultrasound_notes="Grossesse monofœtale évolutive.",
            diagnostic="Grossesse de 20 SA sans particularité.",
        )

    def assert_letterhead(self, pdf_bytes, title):
        pages = pdf_pages(pdf_bytes)
        for text in pages:
            for marker in LETTERHEAD_MARKERS:
                self.assertIn(marker, text)
            self.assertNotIn(FAKE_HEADER, text)
            self.assertNotIn("ORDONNANCE", text)  # le fond vierge ne porte pas le titre de l'ordonnance
        self.assertIn(title, pages[0])
        self.assertIn("Khemisset, le", pages[0])
        self.assertIn(f"Page 1 / {len(pages)}", pages[0])
        return pages

    def test_report_follows_consultation_structure(self):
        pages = self.assert_letterhead(services.generate_report_pdf(self.consultation, save_copy=False), "COMPTE RENDU DE CONSULTATION")
        text = pages[0]
        for expected in ("Mme Salma Bennani", "Tension", "11/7", "IMC", "Examen clinique", "Utérus souple",
                         "Échographie", "monofœtale", "Conclusion", "20 SA + 0 j", "Dr Khadija Errmili"):
            self.assertIn(expected, text)
        # Ordre de la consultation : examen clinique, puis échographie, puis conclusion.
        self.assertLess(text.index("Utérus souple"), text.index("monofœtale"))
        self.assertLess(text.index("monofœtale"), text.index("Grossesse de 20 SA"))

    def test_report_lists_quick_exams(self):
        act = MedicalAct.objects.create(cabinet=self.cabinet, name="Frottis cervico-vaginal", price=Decimal("250"), is_quick_exam=True)
        ConsultationAct.objects.create(consultation=self.consultation, act=act, price=act.price)
        text = pdf_pages(services.generate_report_pdf(self.consultation, save_copy=False))[0]
        self.assertIn("Examens complémentaires", text)
        self.assertIn("Frottis cervico-vaginal", text)

    def test_letters(self):
        from apps.clinical.courriers import COURRIER_TYPES

        for courrier in COURRIER_TYPES:
            pdf = services.generate_letter_pdf(self.consultation, courrier["key"], "Chère consœur,\nJe vous adresse ma patiente.", save_copy=False)
            self.assert_letterhead(pdf, courrier["title"].upper())

    def test_long_letter_spans_pages_with_letterhead_on_each(self):
        content = "Je vous adresse ma patiente pour avis. " * 400
        pages = self.assert_letterhead(services.generate_letter_pdf(self.consultation, "letter", content, save_copy=False), "LETTRE")
        self.assertGreater(len(pages), 1)
        self.assertIn(f"Page 2 / {len(pages)}", pages[1])

    def test_patient_record(self):
        pages = self.assert_letterhead(
            services.generate_patient_record_pdf(self.patient, save_copy=False, doctor=self.doctor), "DOSSIER PATIENTE",
        )
        self.assertIn("Historique des consultations", pages[0])

    def test_receipt_has_letterhead_and_no_clinical_data(self):
        invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("300"))
        act = MedicalAct.objects.create(cabinet=self.cabinet, name="Consultation gynécologique", price=Decimal("300"))
        InvoiceItem.objects.create(invoice=invoice, act=act, price=act.price)
        payment = record_payment(invoice, None, "cash", self.doctor)
        pages = self.assert_letterhead(generate_receipt_pdf(payment, save_copy=False), "REÇU DE PAIEMENT")
        self.assertIn("trois cents dirhams", pages[0])
        self.assertNotIn("monofœtale", pages[0])
        self.assertNotIn("Utérus", pages[0])

    def test_prescription_keeps_its_model_without_stray_page_number(self):
        text = pdf_pages(services.generate_prescription_pdf(self.consultation, "Fer 1 cp/j", save_copy=False))[0]
        self.assertIn("ORDONNANCE", text)
        self.assertIn("Khadija Errmili", text)
        self.assertNotIn("1 / 1", text)

    def test_city_is_optional(self):
        self.cabinet.ville = ""
        self.cabinet.save()
        text = pdf_pages(services.generate_report_pdf(self.consultation, save_copy=False))[0]
        self.assertNotIn(", le", text.split("COMPTE RENDU")[1][:40])
