"""Impression sur papier pré-imprimé (profils A4/A5, décalage, page de test) et recettes réservées à la doctoresse."""

import importlib
import io
import json
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, PrintProfile, Profile
from apps.appointments.models import Appointment
from apps.billing.models import CashClosing, Invoice, InvoiceItem, MedicalAct
from apps.billing.services import record_payment
from apps.clinical.models import Consultation, Document
from apps.common.pdf import A5_SIZE, MM
from apps.patients.models import Patient

# Textes du fond (adresse et téléphone du pied de page) : absents d'un PDF d'impression.
LETTERHEAD_MARKERS = ("Khemisset (en face de la Place El Massira)", "dr.errmili.khadija@gmail.com")
A4 = (595.3, 841.9)
A5 = tuple(round(v, 1) for v in A5_SIZE)


def pdf_reader(content):
    return PdfReader(io.BytesIO(content))


def pdf_text(content):
    return "\n".join(page.extract_text() for page in pdf_reader(content).pages)


def page_size(content):
    box = pdf_reader(content).pages[0].mediabox
    return round(float(box.width), 1), round(float(box.height), 1)


def text_origin(content, needle):
    """Position (x, y) en pt, sur la page finale, du premier fragment de texte contenant `needle`."""
    found = []

    def visitor(text, cm, tm, font_dict, font_size):
        if not found and needle in text:
            x, y = tm[4], tm[5]
            found.append((cm[0] * x + cm[2] * y + cm[4], cm[1] * x + cm[3] * y + cm[5]))

    pdf_reader(content).pages[0].extract_text(visitor_text=visitor)
    assert found, f"« {needle} » introuvable dans le PDF"
    return found[0]


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class PrintBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-impression", ville="Khemisset")
        self.doctor = User.objects.create_user(username="dr_print", password="x", first_name="Khadija", last_name="Errmili")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_print", password="x")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.doctor_client = Client()
        self.doctor_client.force_login(self.doctor)
        self.assistant_client = Client()
        self.assistant_client.force_login(self.assistant)

        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Bennani", birth_date=date(1994, 3, 12),
        )
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(), reason="Suivi grossesse",
        )
        self.consultation = Consultation.objects.create(
            appointment=self.appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            diagnostic="Grossesse évolutive sans particularité.",
        )
        Document.objects.create(consultation=self.consultation, document_type="prescription", content="Acide folique 0,4 mg")
        Document.objects.create(consultation=self.consultation, document_type="certificate", content="Certificat de suivi.")
        act = MedicalAct.objects.create(cabinet=self.cabinet, code="CONS", name="Consultation", price=Decimal("300"))
        self.invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("300"))
        InvoiceItem.objects.create(invoice=self.invoice, act=act, price=act.price)
        self.payment = record_payment(self.invoice, Decimal("300"), "cash", self.assistant)

    def document_urls(self):
        """(type de profil, URL du PDF, texte attendu dans le corps) pour les 5 types imprimables."""
        pk = self.appt.pk
        return [
            ("ordonnance", reverse("clinical:prescription_pdf", args=[pk]), "Acide folique"),
            ("compte_rendu", reverse("clinical:report_pdf", args=[pk]), "Grossesse évolutive"),
            ("lettre", reverse("clinical:letter_pdf", args=[pk, "certificate"]), "Certificat de suivi"),
            ("facture", reverse("billing:invoice_pdf", args=[self.invoice.pk]), self.invoice.invoice_number),
            ("recu", reverse("billing:payment_receipt", args=[self.payment.pk]), self.payment.receipt_number),
        ]

    def set_profile(self, document_type, **values):
        profile, _ = PrintProfile.objects.update_or_create(
            cabinet=self.cabinet, document_type=document_type, defaults=values,
        )
        return profile


class PrintProfileDefaultsTest(PrintBase):
    def test_defaults_are_five_a4_profiles_without_offset(self):
        profiles = PrintProfile.ensure_defaults(self.cabinet)
        self.assertEqual([p.document_type for p in profiles], PrintProfile.DocumentType.values)
        self.assertEqual(len(PrintProfile.DocumentType.values), 5)
        for profile in profiles:
            self.assertEqual((profile.format, profile.decalage_x_mm, profile.decalage_y_mm), ("A4", 0, 0))

    def test_data_migration_creates_profiles_for_existing_cabinet(self):
        migration = importlib.import_module("apps.accounts.migrations.0009_print_profiles_defaults")
        migration.create_default_profiles(django_apps, None)
        migration.create_default_profiles(django_apps, None)  # idempotente
        self.assertEqual(PrintProfile.objects.filter(cabinet=self.cabinet).count(), 5)
        self.assertFalse(PrintProfile.objects.filter(cabinet=self.cabinet).exclude(format="A4").exists())


class PrintModeTest(PrintBase):
    def test_print_has_no_background_and_no_preprinted_title_for_all_five_types(self):
        for document_type, url, body in self.document_urls():
            with self.subTest(document=document_type):
                response = self.doctor_client.get(url, {"mode": "impression"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/pdf")
                text = pdf_text(response.content)
                for marker in LETTERHEAD_MARKERS:
                    self.assertNotIn(marker, text)  # aucun fond
                for title in ("ORDONNANCE", "COMPTE RENDU", "FACTURE", "REÇU DE PAIEMENT", "Khemisset, le"):
                    self.assertNotIn(title, text)  # déjà imprimés sur la feuille
                if document_type == "lettre":
                    # La feuille ne dit pas de quel courrier il s'agit : son titre est imprimé avec le texte.
                    self.assertIn("CERTIFICAT MÉDICAL", text)
                else:
                    self.assertNotIn("CERTIFICAT", text)
                self.assertIn(body, text)
                self.assertIn("Bennani", text)
                self.assertEqual(page_size(response.content), A4)

    def test_letterhead_pdf_still_available_for_all_five_types(self):
        for document_type, url, body in self.document_urls():
            with self.subTest(document=document_type):
                text = pdf_text(self.doctor_client.get(url).content)
                self.assertIn(LETTERHEAD_MARKERS[0], text)
                self.assertIn(body, text)

    def test_date_is_printed_on_the_date_line(self):
        url = reverse("clinical:report_pdf", args=[self.appt.pk])
        content = self.doctor_client.get(url, {"mode": "impression"}).content
        date_label = timezone.localtime(self.consultation.appointment.date).strftime("%Y")
        x, y = text_origin(content, date_label)
        self.assertAlmostEqual(x, 284, delta=3)  # pointillés de « Khemisset, le … »
        self.assertTrue(842 - 205 < y < 842 - 180)

    def test_a5_profile_gives_a5_page_in_both_modes(self):
        for document_type, url, _ in self.document_urls():
            self.set_profile(document_type, format="A5")
            with self.subTest(document=document_type):
                printed = self.doctor_client.get(url, {"mode": "impression"}).content
                letterhead = self.doctor_client.get(url).content
                self.assertEqual(page_size(printed), A5)
                self.assertEqual(page_size(letterhead), A5)
                self.assertIn(LETTERHEAD_MARKERS[0], pdf_text(letterhead))

    def test_a5_scales_coordinates(self):
        url = reverse("clinical:report_pdf", args=[self.appt.pk])
        a4_x, a4_y = text_origin(self.doctor_client.get(url, {"mode": "impression"}).content, "Patiente")
        self.set_profile("compte_rendu", format="A5")
        a5_x, a5_y = text_origin(self.doctor_client.get(url, {"mode": "impression"}).content, "Patiente")
        self.assertAlmostEqual(a5_x, a4_x * 0.7071, delta=0.5)
        # En A5 le texte est agrandi (lisibilité) : sa ligne de base descend de quelques points
        # dans le même cadre, qui lui reste exactement réduit.
        self.assertAlmostEqual(a5_y, a4_y * 0.7071, delta=4)
        self.assertLessEqual(a5_y, a4_y * 0.7071)

    def test_offset_is_applied_to_print_only(self):
        url = reverse("billing:invoice_pdf", args=[self.invoice.pk])
        before = text_origin(self.doctor_client.get(url, {"mode": "impression"}).content, "Patiente")
        letterhead_before = text_origin(self.doctor_client.get(url).content, "Patiente")
        self.set_profile("facture", decalage_x_mm=Decimal("10"), decalage_y_mm=Decimal("5"))
        after = text_origin(self.doctor_client.get(url, {"mode": "impression"}).content, "Patiente")
        self.assertAlmostEqual(after[0] - before[0], 10 * MM, delta=0.1)  # vers la droite
        self.assertAlmostEqual(after[1] - before[1], -5 * MM, delta=0.1)  # vers le bas
        self.assertEqual(text_origin(self.doctor_client.get(url).content, "Patiente"), letterhead_before)

    def test_letters_share_the_lettre_profile(self):
        self.set_profile("lettre", format="A5")
        for letter in ("letter", "certificate", "preanesthesia"):
            url = reverse("clinical:letter_pdf", args=[self.appt.pk, letter])
            self.assertEqual(page_size(self.doctor_client.get(url, {"mode": "impression"}).content), A5)

    def test_assistant_prints_receipt_and_invoice(self):
        for url in (reverse("billing:payment_receipt", args=[self.payment.pk]), reverse("billing:invoice_pdf", args=[self.invoice.pk])):
            response = self.assistant_client.get(url, {"mode": "impression"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(LETTERHEAD_MARKERS[0], pdf_text(response.content))

    def test_patient_record_stays_letterhead_only(self):
        url = reverse("clinical:patient_record_pdf", args=[self.appt.pk])
        self.assertIn(LETTERHEAD_MARKERS[0], pdf_text(self.doctor_client.get(url, {"mode": "impression"}).content))

    def test_print_buttons_show_real_size_reminder(self):
        html = self.doctor_client.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        self.assertIn("?mode=impression", html)
        self.assertIn("PDF avec en-tête", html)
        self.assertIn("Taille réelle (100 %)", html)


class TestPageAndSettingsTest(PrintBase):
    def test_test_page_without_background_at_profile_format(self):
        url = reverse("accounts:print_test_page", args=["ordonnance"])
        response = self.doctor_client.get(url)
        self.assertEqual(response.status_code, 200)
        text = pdf_text(response.content)
        self.assertNotIn(LETTERHEAD_MARKERS[0], text)
        self.assertEqual(text.count("Ligne d'exemple"), 3)
        self.assertEqual(page_size(response.content), A4)

        self.set_profile("ordonnance", format="A5", decalage_x_mm=Decimal("2"))
        response = self.doctor_client.get(url)
        self.assertEqual(page_size(response.content), A5)
        self.assertIn("X 2.0 mm", pdf_text(response.content))

    def test_test_page_uses_values_being_edited(self):
        url = reverse("accounts:print_test_page", args=["recu"])
        response = self.doctor_client.get(url, {"recu-format": "A5", "recu-x": "1,5", "recu-y": "-3"})
        self.assertEqual(page_size(response.content), A5)
        self.assertFalse(PrintProfile.objects.filter(cabinet=self.cabinet, format="A5").exists())

    def test_settings_page_saves_cabinet_and_profiles(self):
        response = self.doctor_client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 200)
        for value in PrintProfile.DocumentType.values:
            self.assertContains(response, reverse("accounts:print_test_page", args=[value]))
        data = {"ville": "Khemisset", "inpe": "123456", "ice": "001122334455667"}
        for value in PrintProfile.DocumentType.values:
            data.update({f"{value}-format": "A4", f"{value}-x": "0", f"{value}-y": "0"})
        data.update({"ordonnance-format": "A5", "ordonnance-x": "1,5", "ordonnance-y": "-2"})
        response = self.doctor_client.post(reverse("accounts:settings"), data, HTTP_HX_REQUEST="true")
        self.assertEqual(json.loads(response.headers["HX-Trigger"])["toast"]["message"], "Réglages enregistrés.")
        self.cabinet.refresh_from_db()
        self.assertEqual((self.cabinet.inpe, self.cabinet.ice), ("123456", "001122334455667"))
        profile = PrintProfile.objects.get(cabinet=self.cabinet, document_type="ordonnance")
        self.assertEqual((profile.format, profile.decalage_x_mm, profile.decalage_y_mm), ("A5", Decimal("1.5"), Decimal("-2")))

    def test_settings_rejects_invalid_offset(self):
        response = self.doctor_client.post(
            reverse("accounts:settings"), {"ville": "X", "facture-format": "A4", "facture-x": "abc", "facture-y": "50"},
        )
        self.assertContains(response, "invalide")
        self.cabinet.refresh_from_db()
        self.assertEqual(self.cabinet.ville, "Khemisset")

    def test_settings_link_in_doctor_menu_only(self):
        url = reverse("accounts:settings")
        self.assertContains(self.doctor_client.get(reverse("billing:index")), url)
        self.assertNotContains(self.assistant_client.get(reverse("billing:index")), url)


class RevenueReservedToDoctorTest(PrintBase):
    """L'assistante encaisse sans jamais voir un total ; le contrôle est côté serveur."""

    def setUp(self):
        super().setUp()
        self.pending = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("450"))
        other = Patient.objects.create(cabinet=self.cabinet, first_name="Nadia", last_name="Alaoui")
        self.paid_other = Invoice.objects.create(cabinet=self.cabinet, patient=other, total_amount=Decimal("275"))
        record_payment(self.paid_other, Decimal("275"), "card", self.assistant)

    def test_doctor_pages_forbidden_to_assistant(self):
        forbidden = [
            reverse("billing:daily_revenue"),
            reverse("billing:reports"),
            reverse("billing:export_xlsx"),
            reverse("billing:export_pdf"),
            reverse("accounts:settings"),
            reverse("accounts:print_test_page", args=["facture"]),
        ]
        for url in forbidden:
            with self.subTest(url=url):
                self.assertEqual(self.assistant_client.get(url).status_code, 403)
        self.assertEqual(self.assistant_client.post(reverse("accounts:settings"), {"ville": "X"}).status_code, 403)
        self.assertEqual(self.doctor_client.get(reverse("billing:daily_revenue")).status_code, 200)

    def test_no_total_in_assistant_html(self):
        pages = [
            reverse("appointments:assistant_dashboard"),
            reverse("billing:index"),
            reverse("billing:cash_register"),
        ]
        for url in pages:
            with self.subTest(url=url):
                html = self.assistant_client.get(url).content.decode()
                for forbidden in ("encaissés aujourd'hui", "Total encaissé", "Total du jour", "Par mode de paiement",
                                  "Espèces attendues", "Écart", "status-count-", "575,00", "Recettes du jour"):
                    self.assertNotIn(forbidden, html)

    def test_assistant_billing_lists_pending_and_searches_one_invoice(self):
        url = reverse("billing:index")
        response = self.assistant_client.get(url)
        self.assertEqual(list(response.context["invoices"]), [self.pending])
        self.assertNotContains(response, self.paid_other.invoice_number)  # aucune liste des payées
        self.assertNotContains(response, self.invoice.invoice_number)

        response = self.assistant_client.get(url, {"q": "alaoui"})
        self.assertEqual(list(response.context["invoices"]), [self.paid_other])
        self.assertContains(response, reverse("billing:invoice_pdf", args=[self.paid_other.pk]) + "?mode=impression")
        payment = self.paid_other.payments.get()
        self.assertContains(response, reverse("billing:payment_receipt", args=[payment.pk]))

        # Le filtre par statut n'est pas ouvert à l'assistante.
        response = self.assistant_client.get(url, {"statut": "paid"})
        self.assertEqual(list(response.context["invoices"]), [self.pending])

    def test_blind_closing(self):
        caisse = self.assistant_client.get(reverse("billing:cash_register")).content.decode()
        self.assertIn("Espèces comptées", caisse)
        self.assertNotIn("DH</span></span>", caisse)
        self.assertNotIn("575", caisse)

        response = self.assistant_client.post(
            reverse("billing:cash_close"),
            {"date": timezone.localdate().isoformat(), "counted_cash": "250"}, HTTP_HX_REQUEST="true",
        )
        html = response.content.decode()
        self.assertEqual(json.loads(response.headers["HX-Trigger"])["toast"]["message"], "Clôture enregistrée.")
        self.assertIn("Clôture enregistrée", html)
        for forbidden in ("250,00", "300,00", "-50,00", " DH", "Écart", "écart", "attendu"):
            self.assertNotIn(forbidden, html)

        closing = CashClosing.objects.get(cabinet=self.cabinet)
        self.assertEqual((closing.expected_cash, closing.difference), (Decimal("300"), Decimal("-50")))
        # La doctoresse voit l'écart dans « Recettes du jour ».
        doctor_html = self.doctor_client.get(reverse("billing:daily_revenue")).content.decode()
        self.assertIn("Écart", doctor_html)
        self.assertIn("-50,00", doctor_html)
        self.assertIn("Total du jour", doctor_html)

    def test_doctor_daily_revenue_navigation_and_caisse_redirect(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        response = self.doctor_client.get(reverse("billing:daily_revenue"), {"date": yesterday})
        self.assertEqual(response.context["day"].isoformat(), yesterday)
        self.assertIsNotNone(response.context["next_day"])
        response = self.doctor_client.get(reverse("billing:cash_register"))
        self.assertRedirects(response, reverse("billing:daily_revenue"))

    def test_menu_entries_per_role(self):
        doctor_html = self.doctor_client.get(reverse("billing:index")).content.decode()
        assistant_html = self.assistant_client.get(reverse("billing:index")).content.decode()
        self.assertIn("Recettes du jour", doctor_html)
        self.assertNotIn("Recettes du jour", assistant_html)
        self.assertIn(reverse("billing:cash_register"), assistant_html)
