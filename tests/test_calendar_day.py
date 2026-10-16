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


@override_settings(ALLOWED_HOSTS=["testserver"])
class CalendarDayEveningTest(TestCase):
    """Les RDV du soir (après 18:30) élargissent la grille au lieu de s'empiler en bas."""

    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Soir", slug="cabinet-soir")
        user = User.objects.create_user(username="assist_soir", password="testpass123")
        Profile.objects.update_or_create(user=user, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.client.login(username="assist_soir", password="testpass123")
        self.day = timezone.localdate() + timedelta(days=1)
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="Rim", last_name="Sbai")
        for hour, minute in ((20, 0), (22, 30)):
            Appointment.objects.create(
                cabinet=self.cabinet, patient=patient, duration_minutes=25,
                date=timezone.make_aware(datetime.combine(self.day, time(hour, minute))),
            )

    def test_evening_appointments_get_their_own_rows(self):
        html = self.client.get(reverse("appointments:calendar"), {"view": "day", "date": self.day.isoformat()}).content.decode()
        tops = [float(v) for v in re.findall(r'style="top: ([0-9.]+)%', html)]
        self.assertEqual(len(tops), 2)
        self.assertLess(tops[0], tops[1])
        self.assertLess(tops[1], 100)
        self.assertIn("22:30", html)  # libellé de ligne affiché (grille jusqu'à 23:00)
