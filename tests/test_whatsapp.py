from datetime import datetime, timedelta
from urllib.parse import unquote

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.common import whatsapp
from apps.patients.models import Patient


class WhatsappMessageTest(SimpleTestCase):
    def setUp(self):
        self.cabinet = Cabinet(nom="Cabinet Dr Test")
        self.dt = datetime(2025, 10, 17, 10, 30)  # vendredi

    def test_date_format(self):
        self.assertEqual(whatsapp.format_rdv_datetime(self.dt), "vendredi 17 octobre à 10h30")
        self.assertEqual(whatsapp.format_rdv_datetime(datetime(2026, 8, 3, 9, 5)), "lundi 3 août à 9h05")

    def test_reminder_uses_cabinet_name(self):
        msg = whatsapp.reminder_message("Imane", self.cabinet, self.dt)
        self.assertEqual(
            msg,
            "Bonjour Imane, Cabinet Dr Test vous rappelle votre rendez-vous du vendredi 17 octobre "
            "à 10h30. Merci de confirmer votre présence en répondant à ce message.",
        )
        self.assertNotIn("ERRMILI", msg)

    def test_other_templates(self):
        self.assertIn("est bien enregistré pour le vendredi 17 octobre à 10h30",
                      whatsapp.confirmation_message("Imane", self.cabinet, self.dt))
        self.assertIn("a été déplacé au vendredi 17 octobre à 10h30",
                      whatsapp.rescheduled_message("Imane", self.cabinet, self.dt))
        free = whatsapp.free_message("Imane", self.cabinet, " vos résultats sont disponibles. ")
        self.assertEqual(free, "Bonjour Imane, vos résultats sont disponibles.\n— Cabinet Dr Test")

    def test_missing_cabinet_falls_back(self):
        self.assertIn("Le cabinet vous rappelle", whatsapp.reminder_message("Imane", None, self.dt))

    def test_valid_numbers(self):
        cases = {
            "0612345678": "212612345678",
            "06 12 34 56 78": "212612345678",
            "07-12-34-56-78": "212712345678",
            "+212 6 12 34 56 78": "212612345678",
            "00212612345678": "212612345678",
            "+212 (0)6 12 34 56 78": "212612345678",
            "+33 6 12 34 56 78": "33612345678",
        }
        for raw, expected in cases.items():
            self.assertEqual(whatsapp.whatsapp_phone(raw), expected, raw)

    def test_invalid_numbers(self):
        for raw in ["", "   ", "0522123456", "061234", "06123456789", "212512345678", "abc", "+33 12"]:
            self.assertEqual(whatsapp.whatsapp_phone(raw), "", raw)
            self.assertEqual(whatsapp.whatsapp_link(raw, "x"), "", raw)

    def test_link_encodes_message(self):
        link = whatsapp.whatsapp_link("0612345678", "Bonjour à 10h30")
        self.assertTrue(link.startswith("https://wa.me/212612345678?text="))
        self.assertEqual(unquote(link.split("text=")[1]), "Bonjour à 10h30")


@override_settings(ALLOWED_HOSTS=["testserver"])
class WhatsappFlowTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Sauge", slug="cabinet-sauge")
        self.other = Cabinet.objects.create(nom="Cabinet Autre", slug="cabinet-autre")
        self.assistant = User.objects.create_user(username="sara", password="pw", first_name="Sara")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        self.doctor = User.objects.create_user(username="dr", password="pw", first_name="Khadija")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )
        self.client = Client()
        self.client.login(username="sara", password="pw")

    def _appt(self, days=1, phone="0612345678", cabinet=None, **kwargs):
        cabinet = cabinet or self.cabinet
        patient = Patient.objects.create(cabinet=cabinet, first_name="Imane", last_name="Tazi", phone=phone)
        local = timezone.localtime() + timedelta(days=days)
        date = local.replace(hour=10, minute=30, second=0, microsecond=0)
        return Appointment.objects.create(cabinet=cabinet, patient=patient, date=date, **kwargs)

    def test_appointment_link_uses_cabinet_name(self):
        link = unquote(self._appt().whatsapp_reminder_link)
        self.assertIn("Cabinet Sauge vous rappelle", link)
        self.assertIn("à 10h30", link)

    def test_invalid_number_has_no_link(self):
        appt = self._appt(phone="0522123456")
        self.assertEqual(appt.whatsapp_reminder_link, "")
        self.assertEqual(appt.whatsapp_phone_state, "invalid")
        self.assertEqual(self._appt(phone="").whatsapp_phone_state, "missing")

    def test_send_records_who_and_when(self):
        appt = self._appt()
        response = self.client.post(reverse("appointments:whatsapp_action", args=[appt.pk, "send"]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("simulation", response.headers["HX-Trigger"])
        appt.refresh_from_db()
        self.assertEqual(appt.whatsapp_status, Appointment.WhatsappStatus.SENT)
        self.assertEqual(appt.whatsapp_sent_by, self.assistant)
        self.assertLess(timezone.now() - appt.whatsapp_sent_at, timedelta(seconds=5))
        sent = timezone.localtime(appt.whatsapp_sent_at)
        self.assertEqual(appt.whatsapp_sent_label, f"Envoyé à {sent.hour}h{sent.minute:02d} par Sara")

    def test_panel_shows_sent_label(self):
        appt = self._appt(days=0)
        appt.mark_whatsapp_sent(self.assistant)
        html = self.client.get(reverse("appointments:reception_panel", args=[appt.pk])).content.decode()
        self.assertIn("par Sara", html)
        self.assertNotIn("simulation", html)

    def test_doctor_can_send_too(self):
        appt = self._appt()
        self.client.login(username="dr", password="pw")
        self.client.post(reverse("appointments:whatsapp_action", args=[appt.pk, "send"]))
        appt.refresh_from_db()
        self.assertEqual(appt.whatsapp_sent_by, self.doctor)

    def test_other_cabinet_is_forbidden(self):
        appt = self._appt(cabinet=self.other)
        response = self.client.post(reverse("appointments:whatsapp_action", args=[appt.pk, "send"]))
        self.assertEqual(response.status_code, 404)
        appt.refresh_from_db()
        self.assertIsNone(appt.whatsapp_sent_at)

    def test_relaunch_list(self):
        old = timezone.now() - timedelta(hours=30)
        stale = self._appt(days=1, whatsapp_status="sent", whatsapp_sent_at=old)
        recent = self._appt(days=1, whatsapp_status="sent", whatsapp_sent_at=timezone.now() - timedelta(hours=2))
        confirmed = self._appt(days=2, whatsapp_status="confirmed", whatsapp_sent_at=old)
        missing = self._appt(days=2, phone="")
        invalid = self._appt(days=1, phone="0522123456")
        too_far = self._appt(days=4, whatsapp_status="sent", whatsapp_sent_at=old)
        cancelled = self._appt(days=1, phone="", status=Appointment.Status.CANCELLED)
        foreign = self._appt(days=1, phone="", cabinet=self.other)

        response = self.client.get(reverse("appointments:assistant_dashboard"))
        relaunch = response.context["relaunch_appointments"]
        self.assertEqual({a.pk for a in relaunch}, {stale.pk, missing.pk, invalid.pk})
        for excluded in (recent, confirmed, too_far, cancelled, foreign):
            self.assertNotIn(excluded, relaunch)
        html = response.content.decode()
        self.assertIn("Numéro manquant", html)
        self.assertIn("Numéro à vérifier", html)
        self.assertIn("tel:0522123456", html)
        self.assertIn("Relancer", html)

    def test_relaunch_action_refreshes_timestamp(self):
        appt = self._appt(whatsapp_status="sent", whatsapp_sent_at=timezone.now() - timedelta(hours=30))
        self.client.post(reverse("appointments:whatsapp_action", args=[appt.pk, "relaunch"]))
        appt.refresh_from_db()
        self.assertLess(timezone.now() - appt.whatsapp_sent_at, timedelta(seconds=5))
        response = self.client.get(reverse("appointments:assistant_dashboard"))
        self.assertNotIn(appt, response.context["relaunch_appointments"])

    def test_j1_and_j2_tabs(self):
        j1 = self._appt(days=1)
        j2 = self._appt(days=2)
        response = self.client.get(reverse("appointments:assistant_dashboard"))
        self.assertEqual(response.context["j1_appointments"], [j1])
        self.assertEqual(response.context["j2_appointments"], [j2])
        html = response.content.decode()
        self.assertIn("J+1", html)
        self.assertIn("J+2", html)
        self.assertIn("https://wa.me/212612345678", html)
        self.assertNotIn("simulation", html)
