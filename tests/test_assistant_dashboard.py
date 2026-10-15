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
