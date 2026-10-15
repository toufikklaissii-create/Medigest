import re
from datetime import datetime, time, timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class CalendarDayPositionTest(TestCase):
    """Locale fr : les pourcentages ne doivent jamais sortir avec une virgule dans le CSS."""

    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.assistant = User.objects.create_user(username="assist_cal", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="Nadia", last_name="Bennani")

        self.day = timezone.localdate() + timedelta(days=1)
        # 08:55 → 25 min après 08:30 → 4,17 % : valeur décimale garantie.
        start = timezone.make_aware(datetime.combine(self.day, time(8, 55)))
        Appointment.objects.create(
            cabinet=self.cabinet, patient=patient, date=start, duration_minutes=20, reason="Suivi grossesse"
        )

        self.client = Client()
        self.client.login(username="assist_cal", password="testpass123")

    def test_day_view_styles_use_dot_decimals(self):
        response = self.client.get(
            reverse("appointments:calendar"), {"view": "day", "date": self.day.isoformat()}
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        styles = re.findall(r'style="(top:[^"]*)"', html)
        self.assertTrue(styles, "Aucune carte RDV positionnée dans la vue jour")
        for style in styles:
            self.assertNotIn(",", style, f"Style CSS invalide (virgule locale) : {style}")
        self.assertIn("top: 4.17%", html)
        self.assertIn("Suivi grossesse", html)
