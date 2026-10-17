from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.intake import clean_intake_vitals
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation, Document, pregnancy_dates
from apps.patients.models import Patient

SECRET_DIAGNOSTIC = "DIAG-CONFIDENTIEL-7781"
SECRET_NOTES = "OBS-CONFIDENTIELLE-4410"
SECRET_EXAM = "EXAMEN-CONFIDENTIEL-2290"
SECRET_PRESCRIPTION = "ORDO-CONFIDENTIELLE-5530"


class PregnancyCalculationTest(SimpleTestCase):
    def test_terme_and_due_date(self):
        lmp = date(2026, 3, 1)
        result = pregnancy_dates(lmp, date(2026, 6, 1))  # 92 jours
        self.assertEqual((result["weeks"], result["days"]), (13, 1))
        self.assertEqual(result["due_date"], date(2026, 12, 6))  # DDR + 280 j

    def test_day_zero_and_out_of_range(self):
        lmp = date(2026, 3, 1)
        self.assertEqual(pregnancy_dates(lmp, lmp)["weeks"], 0)
        self.assertIsNone(pregnancy_dates(lmp, lmp - timedelta(days=1)))
        self.assertIsNone(pregnancy_dates(lmp, lmp + timedelta(days=400)))
        self.assertIsNone(pregnancy_dates(None, lmp))


class IntakeValidationTest(SimpleTestCase):
    today = date(2026, 10, 15)

    def test_valid_values_accept_french_decimal_comma(self):
        cleaned, errors, _ = clean_intake_vitals(
            {"blood_pressure": "12/8", "weight_kg": "68,5", "height_cm": "165", "last_menstrual_period": "2026-08-01"},
            self.today,
        )
        self.assertEqual(errors, {})
        self.assertEqual(cleaned["weight_kg"], Decimal("68.50"))
        self.assertEqual(cleaned["height_cm"], Decimal("165.0"))

    def test_invalid_values_get_field_errors(self):
        _, errors, raw = clean_intake_vitals(
            {"blood_pressure": "300/20", "weight_kg": "abc", "height_cm": "9000", "last_menstrual_period": "2027-01-01"},
            self.today,
        )
        self.assertEqual(set(errors), {"blood_pressure", "weight_kg", "height_cm", "last_menstrual_period"})
        self.assertEqual(raw["weight_kg"], "abc")

    def test_blood_pressure_formats(self):
        for ok in ("12/8", "120/80", "13,5/8"):
            self.assertNotIn("blood_pressure", clean_intake_vitals({"blood_pressure": ok}, self.today)[1], ok)
        for ko in ("abc", "8/12", "120", "NaN/80"):
            self.assertIn("blood_pressure", clean_intake_vitals({"blood_pressure": ko}, self.today)[1], ko)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ClinicalRecordFlowTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_rec", password="testpass123")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )
        self.assistant = User.objects.create_user(username="assist_rec", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Sara", last_name="Idrissi")
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(),
            status=Appointment.Status.WAITING, reason="Suivi grossesse",
        )
        self.doctor_client = Client()
        self.doctor_client.login(username="dr_rec", password="testpass123")
        self.assistant_client = Client()
        self.assistant_client.login(username="assist_rec", password="testpass123")

    def _post_vitals(self, **data):
        return self.assistant_client.post(
            reverse("appointments:save_intake_vitals", args=[self.appt.pk]), data
        )

    def test_assistant_intake_flows_to_doctor_constants_block(self):
        lmp = timezone.localdate() - timedelta(days=12 * 7 + 3)
        response = self._post_vitals(
            blood_pressure="12/8", weight_kg="64", height_cm="160",
            last_menstrual_period=lmp.isoformat(), medical_history_add="Césarienne 2022",
        )
        self.assertEqual(response.status_code, 200)
        self.patient.refresh_from_db()
        # Assistante : ajout daté, jamais de remplacement.
        self.assertEqual(self.patient.medical_history, f"[{timezone.localdate():%d/%m/%Y}] Césarienne 2022")

        html = self.doctor_client.get(
            reverse("clinical:consultation_detail", args=[self.appt.pk])
        ).content.decode()
        self.assertIn("12/8", html)
        self.assertIn("64 kg", html)
        self.assertIn("160 cm", html)
        self.assertIn("25,0", html)  # IMC = 64 / 1,6²
        self.assertIn("12 SA + 3 j", html)
        self.assertIn("Césarienne 2022", html)
        self.assertIn("Date prévue d'accouchement", html)

    def test_invalid_intake_shows_field_errors_without_saving(self):
        response = self._post_vitals(weight_kg="abc", height_cm="165", blood_pressure="999/1")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Le poids doit être un nombre", html)
        self.assertIn("Valeur de tension peu plausible", html)
        self.assertIn('value="abc"', html)
        self.assertFalse(Consultation.objects.filter(appointment=self.appt, height_cm__isnull=False).exists())

    def test_intake_without_history_field_keeps_existing_history(self):
        self.patient.medical_history = "HTA"
        self.patient.save()
        self._post_vitals(weight_kg="60")
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.medical_history, "HTA")

    def test_section_order_on_consultation_sheet(self):
        html = self.doctor_client.get(
            reverse("clinical:consultation_detail", args=[self.appt.pk])
        ).content.decode()
        html = html[html.index('id="consultation-form"'):]
        order = ["Examen clinique", "Échographie", "Examens complémentaires",
                 "Conclusion &amp; interprétation", "Ordonnances", "Facturation"]
        positions = [html.index(label) for label in order]
        self.assertEqual(positions, sorted(positions))

    def test_doctor_saves_clinical_exam(self):
        self.doctor_client.post(
            reverse("clinical:consultation_detail", args=[self.appt.pk]),
            {"action": "draft", "clinical_exam": "Abdomen souple"},
        )
        self.assertEqual(Consultation.objects.get(appointment=self.appt).clinical_exam, "Abdomen souple")

    def test_assistant_never_reaches_clinical_data(self):
        consultation = Consultation.objects.create(
            appointment=self.appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            diagnostic=SECRET_DIAGNOSTIC, clinical_notes=SECRET_NOTES, clinical_exam=SECRET_EXAM,
        )
        Document.objects.create(
            consultation=consultation, document_type=Document.DocumentType.PRESCRIPTION,
            content=SECRET_PRESCRIPTION,
        )

        forbidden = [
            reverse("clinical:doctor_dashboard"),
            reverse("clinical:consultation_detail", args=[self.appt.pk]),
            reverse("clinical:prescription_pdf", args=[self.appt.pk]),
            reverse("clinical:report_pdf", args=[self.appt.pk]),
            reverse("clinical:patient_record_pdf", args=[self.appt.pk]),
            reverse("clinical:upload_patient_document", args=[self.appt.pk]),
            reverse("patients:patient_full_archive", args=[self.patient.pk]),
        ]
        for url in forbidden:
            self.assertEqual(self.assistant_client.get(url).status_code, 403, url)

        visible = [
            reverse("appointments:assistant_dashboard"),
            reverse("appointments:calendar"),
            reverse("appointments:appointment_drawer", args=[self.appt.pk]),
            reverse("appointments:intake_vitals_modal", args=[self.appt.pk]),
            reverse("patients:index"),
            reverse("patients:edit_patient", args=[self.patient.pk]),
            reverse("patients:patient_documents", args=[self.patient.pk]),
        ]
        responses = [self.assistant_client.get(url) for url in visible]
        responses.append(self._post_vitals(blood_pressure="12/8"))
        for url, response in zip(visible + ["save_intake_vitals"], responses):
            self.assertEqual(response.status_code, 200, url)
            html = response.content.decode()
            for secret in (SECRET_DIAGNOSTIC, SECRET_NOTES, SECRET_EXAM, SECRET_PRESCRIPTION):
                self.assertNotIn(secret, html, f"{secret} visible par l'assistante sur {url}")

        consultation.refresh_from_db()
        self.assertEqual(consultation.diagnostic, SECRET_DIAGNOSTIC)
        self.assertEqual(consultation.clinical_exam, SECRET_EXAM)
