from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class AssistantDashboardTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.assistant = User.objects.create_user(username="assist_dash", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Imane", last_name="Tazi")
        self.client = Client()
        self.client.login(username="assist_dash", password="testpass123")

    def _appt(self, status):
        return Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient,
            date=timezone.now() + timedelta(minutes=1), status=status,
        )

    def test_received_kpi_ignores_scheduled_and_cancelled(self):
        S = Appointment.Status
        for status in (S.SCHEDULED, S.SCHEDULED, S.CANCELLED, S.ARRIVED, S.WAITING, S.IN_CONSULTATION, S.COMPLETED):
            self._appt(status)
        response = self.client.get(reverse("appointments:assistant_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_total"], 4)

    def test_zero_invoice_shows_badge_instead_of_pay_button(self):
        Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("0"))
        html = self.client.get(reverse("appointments:assistant_dashboard")).content.decode()
        self.assertIn("Aucun acte", html)
        self.assertNotIn("Encaisser la facture", html)

    def test_reminder_button_label(self):
        html = self.client.get(reverse("appointments:assistant_dashboard")).content.decode()
        self.assertNotIn("Simuler envoi rappel", html)

    def _completed_with_invoice(self, amount):
        from apps.clinical.models import Consultation

        doctor = User.objects.create_user(username=f"dr_{amount}", password="x")
        Profile.objects.update_or_create(user=doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        appt = self._appt(Appointment.Status.COMPLETED)
        invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal(amount))
        Consultation.objects.create(
            appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=doctor,
            invoice=invoice, diagnostic="DIAG-SECRET-ACCUEIL",
        )
        return appt, invoice

    def test_timeline_contextual_actions(self):
        self._appt(Appointment.Status.SCHEDULED)
        self._appt(Appointment.Status.ARRIVED)
        self._appt(Appointment.Status.WAITING)
        self._completed_with_invoice("300")
        html = self.client.get(reverse("appointments:assistant_dashboard")).content.decode()
        self.assertIn('id="timeline"', html)
        self.assertIn('hx-trigger="every 15s', html)
        for label in ("Arrivée", "Mettre en attente", "Attend le médecin", "Encaisser 300,00"):
            self.assertIn(label, html)
        self.assertNotIn("Rechercher…", html)  # 2e barre de recherche (décorative) supprimée
        self.assertNotIn(">\n            Live\n", html)

    def test_advance_from_timeline_returns_timeline_with_counters(self):
        appt = self._appt(Appointment.Status.SCHEDULED)
        response = self.client.post(
            reverse("appointments:advance_status", args=[appt.pk]), HTTP_HX_REQUEST="true", HTTP_HX_TARGET="timeline"
        )
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.ARRIVED)
        html = response.content.decode()
        self.assertIn('id="timeline"', html)
        self.assertIn('id="day-counters" role="group" aria-label="Activité du jour" hx-swap-oob="true"', html)
        self.assertIn("panel-refresh", response["HX-Trigger"])

    def test_panel_shows_payment_without_clinical_data(self):
        appt, invoice = self._completed_with_invoice("450")
        html = self.client.get(reverse("appointments:reception_panel", args=[appt.pk])).content.decode()
        self.assertIn(reverse("billing:pay_invoice", args=[invoice.pk]), html)
        for method in ('value="cash"', 'value="card"', 'value="check"'):
            self.assertIn(method, html)
        self.assertNotIn("DIAG-SECRET-ACCUEIL", html)
        timeline = self.client.get(reverse("appointments:reception_timeline")).content.decode()
        self.assertNotIn("DIAG-SECRET-ACCUEIL", timeline)

    def test_panel_is_scoped_to_cabinet(self):
        other = Cabinet.objects.create(nom="Autre", slug="autre")
        patient = Patient.objects.create(cabinet=other, first_name="A", last_name="B")
        appt = Appointment.objects.create(cabinet=other, patient=patient, date=timezone.now())
        self.assertEqual(self.client.get(reverse("appointments:reception_panel", args=[appt.pk])).status_code, 404)

    def test_dh_filter(self):
        from apps.common.templatetags.medigest_format import dh

        self.assertEqual(dh(Decimal("1250")), "1 250,00 DH")
        self.assertEqual(dh(0), "0,00 DH")

    def test_amounts_use_non_breaking_spaces(self):
        Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("1100"))
        expected = "1 100,00 DH"
        self.assertIn(expected, self.client.get(reverse("appointments:assistant_dashboard")).content.decode())
        self.assertIn(expected, self.client.get(reverse("billing:index")).content.decode())
