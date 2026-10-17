"""Réglages issus des réponses de Dr Errmili : antécédents en ajout seul, espèces, prix libre,
horaires, contrôle gratuit, PDF comptable, téléphone WhatsApp."""

import importlib
import io
import json
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.appointments.views import hours_warning
from apps.billing.models import Invoice, InvoiceItem, MedicalAct, Payment
from apps.billing.services import BillingError, record_payment
from apps.clinical.models import Consultation
from apps.clinical.services import free_control_candidate
from apps.common import whatsapp
from apps.patients.history import append_note
from apps.patients.models import Patient

SECRET_HISTORY = "Diabète gestationnel confidentiel"
SECRET_ALLERGY = "Pénicilline confidentielle"


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


@override_settings(ALLOWED_HOSTS=["testserver"])
class ReglagesBase(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Dr ERRMILI", slug="cabinet-reglages")
        self.doctor = User.objects.create_user(username="dr_reg", password="x", first_name="Khadija", last_name="Errmili")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_reg", password="x")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.doctor_client = Client()
        self.doctor_client.force_login(self.doctor)
        self.assistant_client = Client()
        self.assistant_client.force_login(self.assistant)
        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Bennani", phone="0612345678",
            medical_history=SECRET_HISTORY, allergies=SECRET_ALLERGY,
        )
        self.appt = Appointment.objects.create(cabinet=self.cabinet, patient=self.patient, date=timezone.now())
        self.consult = MedicalAct.objects.create(cabinet=self.cabinet, code="CONS", name="Consultation", price=Decimal("300"))
        self.echo = MedicalAct.objects.create(
            cabinet=self.cabinet, code="ECHO", name="Échographie obstétricale", price=Decimal("0"), prix_libre=True,
        )


# ── 1. Antécédents et allergies ──────────────────────────────────────────────

class HistoryBlindToAssistantTest(ReglagesBase):
    def assistant_pages(self):
        Consultation.objects.create(appointment=self.appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor)
        return [
            reverse("patients:edit_patient", args=[self.patient.pk]),
            reverse("patients:create_patient"),
            reverse("patients:index"),
            reverse("appointments:assistant_dashboard"),
            reverse("appointments:reception_panel", args=[self.appt.pk]),
            reverse("appointments:intake_vitals_modal", args=[self.appt.pk]),
            reverse("appointments:appointment_drawer", args=[self.appt.pk]),
            reverse("appointments:patient_search") + "?q=Bennani",
            reverse("appointments:calendar") + "?view=day",
        ]

    def test_no_history_or_allergy_content_in_assistant_html(self):
        for url in self.assistant_pages():
            with self.subTest(url=url):
                response = self.assistant_client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertNotIn(SECRET_HISTORY, html)
                self.assertNotIn(SECRET_ALLERGY, html)
        html = self.assistant_client.get(reverse("patients:edit_patient", args=[self.patient.pk])).content.decode()
        self.assertIn("Antécédents renseignés", html)
        self.assertIn("Allergies renseignées", html)
        self.assertIn('name="medical_history_add"', html)
        self.assertNotIn('name="medical_history"', html)

    def test_empty_fields_say_nothing_entered(self):
        self.patient.medical_history = self.patient.allergies = ""
        self.patient.save()
        html = self.assistant_client.get(reverse("patients:edit_patient", args=[self.patient.pk])).content.decode()
        self.assertIn("Aucun antécédent saisi", html)
        self.assertIn("Aucune allergie saisie", html)

    def test_assistant_edit_appends_without_overwriting(self):
        response = self.assistant_client.post(reverse("patients:edit_patient", args=[self.patient.pk]), {
            "first_name": "Salma", "last_name": "Bennani",
            "medical_history": "ÉCRASÉ", "allergies": "ÉCRASÉ",  # ignorés : l'assistante ne peut qu'ajouter
            "medical_history_add": "Césarienne 2020", "allergies_add": "Iode",
        })
        self.assertEqual(response.status_code, 302)
        self.patient.refresh_from_db()
        today = f"{timezone.localdate():%d/%m/%Y}"
        self.assertEqual(self.patient.medical_history, f"{SECRET_HISTORY}\n[{today}] Césarienne 2020")
        self.assertEqual(self.patient.allergies, f"{SECRET_ALLERGY}\n[{today}] Iode")

    def test_assistant_empty_addition_keeps_existing(self):
        self.assistant_client.post(reverse("patients:edit_patient", args=[self.patient.pk]), {
            "first_name": "Salma", "last_name": "Bennani", "medical_history": "", "allergies": "",
        })
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.medical_history, self.patient.allergies), (SECRET_HISTORY, SECRET_ALLERGY))

    def test_assistant_create_and_intake_only_append(self):
        self.assistant_client.post(reverse("patients:create_patient"), {
            "first_name": "Nadia", "last_name": "Alaoui", "medical_history_add": "HTA", "allergies": "ignoré",
        })
        created = Patient.objects.get(last_name="Alaoui")
        self.assertTrue(created.medical_history.endswith("] HTA"))
        self.assertEqual(created.allergies, "")

        self.assistant_client.post(reverse("appointments:save_intake_vitals", args=[self.appt.pk]), {
            "weight_kg": "60", "medical_history": "ÉCRASÉ", "medical_history_add": "G2P1",
        })
        self.patient.refresh_from_db()
        self.assertTrue(self.patient.medical_history.startswith(SECRET_HISTORY))
        self.assertTrue(self.patient.medical_history.endswith("] G2P1"))
        self.assertNotIn("ÉCRASÉ", self.patient.medical_history)

    def test_create_form_has_no_vitals_fields(self):
        # Les constantes se saisissent à l'arrivée, sur le RDV : jamais à la création ni à l'édition.
        for url in (reverse("patients:create_patient"), reverse("patients:edit_patient", args=[self.patient.pk])):
            for client in (self.assistant_client, self.doctor_client):
                with self.subTest(url=url):
                    html = client.get(url).content.decode()
                    for name in ("blood_pressure", "weight_kg", "height_cm", "last_menstrual_period"):
                        self.assertNotIn(f'name="{name}"', html)

    def test_intake_allergy_appends_without_overwriting(self):
        url = reverse("appointments:save_intake_vitals", args=[self.appt.pk])
        response = self.assistant_client.post(url, {"allergies": "ÉCRASÉ", "allergies_add": "Latex"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="allergies_add"', html)
        self.assertNotIn('name="allergies"', html)
        self.assertIn("Allergies renseignées", html)
        self.assertNotIn(SECRET_ALLERGY, html)
        self.assertNotIn("Latex", html)
        self.patient.refresh_from_db()
        today = f"{timezone.localdate():%d/%m/%Y}"
        self.assertEqual(self.patient.allergies, f"{SECRET_ALLERGY}\n[{today}] Latex")
        modal = self.assistant_client.get(reverse("appointments:intake_vitals_modal", args=[self.appt.pk])).content.decode()
        self.assertIn('name="allergies_add"', modal)
        self.assertNotIn(SECRET_ALLERGY, modal)
        self.assertNotIn("Latex", modal)

    def test_doctor_sees_and_replaces(self):
        html = self.doctor_client.get(reverse("patients:edit_patient", args=[self.patient.pk])).content.decode()
        self.assertIn(SECRET_HISTORY, html)
        self.assertIn(SECRET_ALLERGY, html)
        self.doctor_client.post(reverse("patients:edit_patient", args=[self.patient.pk]), {
            "first_name": "Salma", "last_name": "Bennani", "medical_history": "Revu", "allergies": "",
        })
        self.patient.refresh_from_db()
        self.assertEqual((self.patient.medical_history, self.patient.allergies), ("Revu", ""))

    def test_append_note_format(self):
        day = datetime(2026, 10, 3).date()
        self.assertEqual(append_note("", "Iode", day), "[03/10/2026] Iode")
        self.assertEqual(append_note("A", "  ", day), "A")


# ── 2. Espèces uniquement ────────────────────────────────────────────────────

class CashOnlyTest(ReglagesBase):
    def setUp(self):
        super().setUp()
        self.cabinet.modes_paiement = ["cash"]
        self.cabinet.paiement_partiel = False
        self.cabinet.save()
        self.invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("300"))
        InvoiceItem.objects.create(invoice=self.invoice, act=self.consult, price=Decimal("300"))

    def test_modal_is_single_cash_button(self):
        html = self.assistant_client.get(reverse("billing:pay_invoice", args=[self.invoice.pk])).content.decode()
        self.assertIn("Encaisser 300,00 DH en espèces", html)
        self.assertNotIn('name="amount"', html)
        self.assertNotIn("Carte", html)
        self.assertEqual(html.count('type="submit"'), 2)  # encaisser + envoi d'un écart (formulaire séparé)
        panel = self.assistant_client.get(reverse("appointments:reception_panel", args=[self.appt.pk]))
        self.assertEqual(panel.status_code, 200)

    def test_one_click_payment_settles_in_cash(self):
        response = self.assistant_client.post(
            reverse("billing:pay_invoice", args=[self.invoice.pk]), {"payment_method": "cash"}, HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, Invoice.Status.PAID)
        self.assertEqual(self.invoice.payments.get().method, "cash")

    def test_server_refuses_other_modes_and_partial(self):
        with self.assertRaises(BillingError):
            record_payment(self.invoice, None, "card", self.assistant)
        with self.assertRaises(BillingError):
            record_payment(self.invoice, Decimal("100"), "cash", self.assistant)
        self.assertFalse(Payment.objects.exists())

    def test_other_modes_reactivable_in_settings(self):
        self.cabinet.modes_paiement = ["cash", "card"]
        self.cabinet.paiement_partiel = True
        self.cabinet.save()
        html = self.assistant_client.get(reverse("billing:pay_invoice", args=[self.invoice.pk])).content.decode()
        self.assertIn("Carte", html)
        self.assertIn('name="amount"', html)
        record_payment(self.invoice, Decimal("100"), "card", self.assistant)

    def test_data_migration_sets_errmili_cash_only(self):
        errmili = Cabinet.objects.create(nom="Dr Errmili", slug="cabinet-dr-errmili")
        migration = importlib.import_module("apps.accounts.migrations.0011_cabinet_errmili_reglages")
        migration.apply_settings(django_apps, None)
        errmili.refresh_from_db()
        self.assertEqual((errmili.modes_paiement, errmili.paiement_partiel), (["cash"], False))
        self.assertEqual(errmili.telephone_whatsapp, "06 66 54 69 54")


# ── 3. Tarifs : prix libre ───────────────────────────────────────────────────

class FreePriceTest(ReglagesBase):
    def post_sheet(self, action="validate", **extra):
        data = {"action": action, "acts": [str(self.consult.pk), str(self.echo.pk)], **extra}
        return self.doctor_client.post(reverse("clinical:consultation_detail", args=[self.appt.pk]), data, follow=True)

    def test_validation_refused_without_price(self):
        response = self.post_sheet(**{f"price_{self.echo.pk}": ""})
        self.assertContains(response, "Indiquez le prix de : Échographie obstétricale")
        consultation = Consultation.objects.get(appointment=self.appt)
        self.assertEqual(consultation.status, Consultation.Status.DRAFT)
        self.assertIsNone(consultation.invoice)

    def test_validation_accepted_with_price(self):
        self.post_sheet(**{f"price_{self.echo.pk}": "450"})
        consultation = Consultation.objects.get(appointment=self.appt)
        self.assertEqual(consultation.status, Consultation.Status.VALIDATED)
        self.assertEqual(consultation.invoice.total_amount, Decimal("750"))

    def test_cockpit_price_field_is_empty_for_free_price_act(self):
        html = self.doctor_client.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        acts = json.loads(html.split('id="acts-data" type="application/json">')[1].split("</script>")[0])
        by_id = {a["id"]: a for a in acts}
        self.assertEqual(by_id[self.echo.pk]["line_price"], "")
        self.assertEqual(by_id[self.consult.pk]["line_price"], 300.0)
        self.assertIn("Prix libre", html)

    def test_tariffs_page_shows_and_toggles_free_price(self):
        self.assertContains(self.doctor_client.get(reverse("billing:tariffs")), "Prix libre")
        self.doctor_client.post(reverse("billing:tariff_row", args=[self.consult.pk]), {
            "code": "CONS", "name": "Consultation", "price": "", "is_active": "on", "prix_libre": "on",
        })
        self.consult.refresh_from_db()
        self.assertTrue(self.consult.prix_libre)
        self.doctor_client.post(reverse("billing:tariff_row", args=[self.consult.pk]), {
            "code": "CONS", "name": "Consultation", "price": "300", "is_active": "on",
        })
        self.consult.refresh_from_db()
        self.assertEqual((self.consult.prix_libre, self.consult.price), (False, Decimal("300")))

    def test_data_migration_consultation_fixed_others_free(self):
        errmili = Cabinet.objects.create(nom="Dr Errmili", slug="cabinet-dr-errmili")
        cons = MedicalAct.objects.create(cabinet=errmili, code="CONS_GYN", name="Consultation gynécologique", price=Decimal("250"))
        frottis = MedicalAct.objects.create(cabinet=errmili, code="FROTTIS", name="Frottis", price=Decimal("250"))
        migration = importlib.import_module("apps.billing.migrations.0010_tarifs_prix_libre")
        migration.apply_tariffs(django_apps, None)
        cons.refresh_from_db()
        frottis.refresh_from_db()
        self.assertEqual((cons.prix_libre, cons.price), (False, Decimal("300")))
        self.assertTrue(frottis.prix_libre)
        self.consult.refresh_from_db()
        self.assertFalse(self.consult.prix_libre)  # autres cabinets inchangés


# ── 4. Horaires ──────────────────────────────────────────────────────────────

class OpeningHoursTest(ReglagesBase):
    def next_weekday(self, weekday):
        day = timezone.localdate() + timedelta(days=1)
        while day.weekday() != weekday:
            day += timedelta(days=1)
        return day

    def day_slots(self, day):
        response = self.assistant_client.get(reverse("appointments:calendar"), {"view": "day", "date": day.isoformat()})
        return response.context["slots"]

    def test_day_grid_follows_opening_hours(self):
        slots = self.day_slots(self.next_weekday(0))
        self.assertEqual((slots[0], slots[-1]), (time(9, 0), time(17, 0)))
        slots = self.day_slots(self.next_weekday(5))
        self.assertEqual((slots[0], slots[-1]), (time(9, 0), time(13, 0)))

    def test_grid_still_extends_for_out_of_hours_appointment(self):
        monday = self.next_weekday(0)
        Appointment.objects.create(cabinet=self.cabinet, patient=self.patient, date=aware(monday, 19))
        self.assertEqual(self.day_slots(monday)[-1], time(20, 0))

    def test_out_of_hours_and_sunday_warn_without_blocking(self):
        monday, sunday = self.next_weekday(0), self.next_weekday(6)
        self.assertIsNone(hours_warning(self.cabinet, aware(monday, 10)))
        self.assertIn("hors des horaires", hours_warning(self.cabinet, aware(monday, 18)))
        self.assertIn("13:00", hours_warning(self.cabinet, aware(self.next_weekday(5), 14)))
        self.assertIn("dimanche", hours_warning(self.cabinet, aware(sunday, 10)))

        response = self.assistant_client.post(reverse("appointments:create_appointment_ajax"), {
            "patient": self.patient.pk, "date": sunday.isoformat(), "time": "10:00", "reason": "Contrôle",
        })
        toast = json.loads(response.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["type"], "warning")
        self.assertIn("fermé le dimanche", toast["message"])
        self.assertTrue(Appointment.objects.filter(date=aware(sunday, 10)).exists())

        response = self.assistant_client.post(reverse("appointments:create_appointment_ajax"), {
            "patient": self.patient.pk, "date": monday.isoformat(), "time": "10:00",
        })
        self.assertEqual(json.loads(response.headers["HX-Trigger"])["toast"]["type"], "success")

    def test_hours_editable_in_settings(self):
        data = {
            "reglages_cabinet": "1", "ville": "Khemisset", "modes_paiement": ["cash"], "heure_ouverture": "08:30",
            "heure_fermeture": "18:00", "heure_fermeture_samedi": "12:30", "controle_gratuit_jours": "15",
            "telephone_whatsapp": "06 00 00 00 00",
        }
        response = self.doctor_client.post(reverse("accounts:settings"), data, HTTP_HX_REQUEST="true")
        self.assertEqual(json.loads(response.headers["HX-Trigger"])["toast"]["message"], "Réglages enregistrés.")
        self.cabinet.refresh_from_db()
        self.assertEqual(self.cabinet.heure_ouverture, time(8, 30))
        self.assertEqual(self.cabinet.heure_fermeture_samedi, time(12, 30))
        self.assertFalse(self.cabinet.dimanche_ferme)
        self.assertEqual((self.cabinet.controle_gratuit_jours, self.cabinet.modes_paiement), (15, ["cash"]))
        self.assertFalse(self.cabinet.paiement_partiel)

    def test_settings_reject_invalid_values(self):
        response = self.doctor_client.post(reverse("accounts:settings"), {
            "reglages_cabinet": "1", "heure_ouverture": "18:00", "heure_fermeture": "09:00",
            "heure_fermeture_samedi": "13:00", "controle_gratuit_jours": "abc",
        })
        self.assertContains(response, "Activez au moins un mode de paiement")
        self.assertContains(response, "après l&#x27;ouverture")
        self.cabinet.refresh_from_db()
        self.assertEqual(self.cabinet.heure_ouverture, time(9, 0))

    def test_new_settings_forbidden_to_assistant(self):
        self.assertEqual(self.assistant_client.post(reverse("accounts:settings"), {"reglages_cabinet": "1"}).status_code, 403)


# ── 5. Contrôle gratuit ──────────────────────────────────────────────────────

class FreeControlTest(ReglagesBase):
    def previous_consultation(self, days_ago, **invoice_fields):
        previous = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=self.appt.date - timedelta(days=days_ago),
        )
        consultation = Consultation.objects.create(
            appointment=previous, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
        )
        invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("300"), **invoice_fields)
        Consultation.objects.filter(pk=consultation.pk).update(invoice=invoice)
        return previous

    def current(self):
        consultation, _ = Consultation.objects.get_or_create(
            appointment=self.appt, defaults={"patient": self.patient, "cabinet": self.cabinet, "doctor": self.doctor},
        )
        return consultation

    def test_19_days_suggests_free_control(self):
        previous = self.previous_consultation(19)
        candidate = free_control_candidate(self.current())
        self.assertEqual(candidate["days"], 19)
        html = self.doctor_client.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        label = f"{timezone.localtime(previous.date):%d/%m}"
        self.assertIn(f"Contrôle gratuit possible : consultation du {label} (il y a 19 jours)", html)
        billing = json.loads(html.split('id="billing-data" type="application/json">')[1].split("</script>")[0])
        self.assertTrue(billing["free"])  # pré-cochée

    def test_banner_wording_today_yesterday_n_days(self):
        url = reverse("clinical:consultation_detail", args=[self.appt.pk])
        self.current()
        for days, wording in ((0, "(aujourd'hui)"), (1, "(hier)"), (2, "(il y a 2 jours)")):
            with self.subTest(days=days):
                Consultation.objects.exclude(appointment=self.appt).delete()
                previous = self.previous_consultation(days)
                if days == 0:  # même jour, plus tôt
                    Appointment.objects.filter(pk=previous.pk).update(date=self.appt.date - timedelta(seconds=1))
                html = self.doctor_client.get(url).content.decode()
                self.assertIn("Contrôle gratuit possible : consultation du", html)
                self.assertIn(wording, html)
                self.assertNotIn("il y a 0 jour", html)
                self.assertNotIn("il y a 1 jour", html)

    def test_21_days_no_suggestion(self):
        self.previous_consultation(21)
        self.assertIsNone(free_control_candidate(self.current()))
        html = self.doctor_client.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        self.assertNotIn("Contrôle gratuit possible", html)
        billing = json.loads(html.split('id="billing-data" type="application/json">')[1].split("</script>")[0])
        self.assertFalse(billing["free"])

    def test_free_or_cancelled_previous_does_not_count(self):
        self.previous_consultation(5, is_free=True)
        self.previous_consultation(6, status=Invoice.Status.CANCELLED)
        self.assertIsNone(free_control_candidate(self.current()))

    def test_doctor_can_uncheck(self):
        self.previous_consultation(10)
        self.doctor_client.post(reverse("clinical:consultation_detail", args=[self.appt.pk]), {
            "action": "validate", "acts": [str(self.consult.pk)],
        })
        consultation = Consultation.objects.get(appointment=self.appt)
        self.assertFalse(consultation.billing_free)
        self.assertEqual(consultation.invoice.total_amount, Decimal("300"))


# ── 6. PDF mensuel pour le comptable ─────────────────────────────────────────

class AccountantPdfTest(ReglagesBase):
    def test_monthly_pdf_has_journal_free_count_and_total(self):
        paid = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("300"))
        InvoiceItem.objects.create(invoice=paid, act=self.consult, price=Decimal("300"))
        record_payment(paid, None, "cash", self.assistant)
        Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("0"), is_free=True)

        month = timezone.localdate().replace(day=1).isoformat()
        response = self.doctor_client.get(reverse("billing:export_pdf"), {"periode": "mois", "date": month})
        self.assertEqual(response.status_code, 200)
        text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(response.content)).pages)
        for expected in ("Journal détaillé", paid.invoice_number, "Salma Bennani", "Consultation", "Espèces",
                         "300,00", "Gratuités / contrôles", "1 gratuité", "Total du mois", "Khemisset (en face"):
            self.assertIn(expected, text)

    def test_reports_page_has_visible_accountant_button(self):
        html = self.doctor_client.get(reverse("billing:reports")).content.decode()
        self.assertIn("PDF mensuel pour le comptable", html)
        self.assertIn("periode=mois", html)


# ── 7. WhatsApp ──────────────────────────────────────────────────────────────

class WhatsappPhoneTest(ReglagesBase):
    def test_reminder_ends_with_cabinet_phone(self):
        self.cabinet.telephone_whatsapp = "06 66 54 69 54"
        message = whatsapp.reminder_message("Salma", self.cabinet, timezone.localtime())
        self.assertTrue(message.endswith("Pour toute question : 06 66 54 69 54"))

    def test_no_phone_no_suffix(self):
        message = whatsapp.reminder_message("Salma", self.cabinet, timezone.localtime())
        self.assertNotIn("Pour toute question", message)
