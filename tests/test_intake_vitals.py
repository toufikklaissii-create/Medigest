from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class IntakeVitalsTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")

        self.doctor = User.objects.create_user(username="dr_vitals", password="testpass123")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )

        self.assistant = User.objects.create_user(username="assist_vitals", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )

        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Vitals"
        )
        self.appointment = Appointment.objects.create(
            cabinet=self.cabinet,
            patient=self.patient,
            date=timezone.now(),
            status=Appointment.Status.WAITING,
        )

        self.client = Client()
        self.client.login(username="assist_vitals", password="testpass123")

    def test_assistant_creates_consultation_and_saves_vitals(self):
        response = self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {
                "blood_pressure": "12/8",
                "weight_kg": "68.5",
                "height_cm": "165",
                "last_menstrual_period": "2026-08-01",
            },
        )
        self.assertEqual(response.status_code, 200)

        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.doctor, self.doctor)
        self.assertEqual(consultation.blood_pressure, "12/8")
        self.assertEqual(str(consultation.weight_kg), "68.50")
        self.assertEqual(str(consultation.height_cm), "165.0")
        self.assertEqual(str(consultation.last_menstrual_period), "2026-08-01")

    def test_assistant_cannot_set_clinical_fields(self):
        self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {
                "blood_pressure": "12/8",
                "diagnostic": "Tentative d'injection de diagnostic",
                "clinical_notes": "Tentative d'injection de notes",
                "ultrasound_notes": "Tentative d'injection d'échographie",
            },
        )
        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.diagnostic, "")
        self.assertEqual(consultation.clinical_notes, "")
        self.assertEqual(consultation.ultrasound_notes, "")

    def test_second_save_updates_existing_consultation_without_duplicate(self):
        url = reverse("appointments:save_intake_vitals", args=[self.appointment.pk])
        self.client.post(url, {"blood_pressure": "12/8", "weight_kg": "68"})
        self.client.post(url, {"blood_pressure": "13/9", "weight_kg": "69"})

        self.assertEqual(Consultation.objects.filter(appointment=self.appointment).count(), 1)
        consultation = Consultation.objects.get(appointment=self.appointment)
        self.assertEqual(consultation.blood_pressure, "13/9")
        self.assertEqual(str(consultation.weight_kg), "69.00")

    def test_doctor_sees_prefilled_vitals(self):
        self.client.post(
            reverse("appointments:save_intake_vitals", args=[self.appointment.pk]),
            {"blood_pressure": "12/8", "weight_kg": "68", "height_cm": "165"},
        )
        doctor_client = Client()
        doctor_client.login(username="dr_vitals", password="testpass123")
        response = doctor_client.get(
            reverse("clinical:consultation_detail", args=[self.appointment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12/8")

    def test_no_doctor_in_cabinet_does_not_crash(self):
        empty_cabinet = Cabinet.objects.create(nom="Cabinet Vide", slug="cabinet-vide")
        assistant_no_doctor = User.objects.create_user(
            username="assist_alone", password="testpass123"
        )
        Profile.objects.update_or_create(
            user=assistant_no_doctor,
            defaults={"role": Profile.Role.ASSISTANT, "cabinet": empty_cabinet},
        )
        patient = Patient.objects.create(
            cabinet=empty_cabinet, first_name="Nadia", last_name="Solo"
        )
        appointment = Appointment.objects.create(
            cabinet=empty_cabinet,
            patient=patient,
            date=timezone.now(),
            status=Appointment.Status.ARRIVED,
        )
        client = Client()
        client.login(username="assist_alone", password="testpass123")

        response = client.post(
            reverse("appointments:save_intake_vitals", args=[appointment.pk]),
            {"blood_pressure": "12/8"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Consultation.objects.filter(appointment=appointment).exists())
