from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.common.templatetags.medigest_format import duree_courte
from apps.patients.models import Patient


class DureeCourteTest(SimpleTestCase):
    def test_formats(self):
        now = timezone.now()
        self.assertEqual(duree_courte(now - timedelta(hours=11, minutes=16), now), "11 h 16")
        self.assertEqual(duree_courte(now - timedelta(hours=1, minutes=5), now), "1 h 05")
        self.assertEqual(duree_courte(now - timedelta(minutes=12), now), "12 min")
        self.assertEqual(duree_courte(now, now), "moins d'1 min")
        self.assertEqual(duree_courte(None), "")


@override_settings(ALLOWED_HOSTS=["testserver"])
class DoctorUiTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_ui", password="testpass123")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="Leila", last_name="Amrani")
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=patient,
            date=timezone.now() - timedelta(minutes=1), status=Appointment.Status.IN_CONSULTATION,
        )
        self.client = Client()
        self.client.login(username="dr_ui", password="testpass123")

    def test_next_patient_in_consultation_shows_resume(self):
        html = self.client.get(reverse("clinical:doctor_dashboard")).content.decode()
        self.assertIn("Reprendre la consultation", html)
        self.assertNotIn("Démarrer la consultation", html)
        self.assertNotIn("heures,", html)

    def test_consultation_page_has_no_nested_form_and_documents_after_exams(self):
        html = self.client.get(
            reverse("clinical:consultation_detail", args=[self.appt.pk])
        ).content.decode()
        main = html[html.index('id="consultation-form"'):]
        main = main[: main.index("</form>")]
        self.assertNotIn("<form", main, "Formulaire imbriqué dans la fiche de consultation")
        self.assertLess(html.index("Examens complémentaires"), html.index("Documents joints"))
        self.assertIn("Choisir un fichier", html)
        self.assertIn('id="doc-upload-form"', html)
