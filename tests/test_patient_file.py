import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import MedicalAct
from apps.clinical.models import Consultation, ConsultationAct, Document
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class PatientFileTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_file", password="testpass123")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="assist_file", password="testpass123")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Salma", last_name="Bennani",
            allergies="Pénicilline", medical_history="G2P1",
        )
        self.doctor_client = Client()
        self.doctor_client.login(username="dr_file", password="testpass123")
        self.assistant_client = Client()
        self.assistant_client.login(username="assist_file", password="testpass123")
        self.url = reverse("clinical:patient_file", args=[self.patient.pk])

    def _visit(self, days_ago, diagnostic, **fields):
        appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, reason="Suivi",
            date=timezone.now() - timedelta(days=days_ago), status=Appointment.Status.COMPLETED,
        )
        return Consultation.objects.create(
            appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            diagnostic=diagnostic, **fields,
        )

    def test_assistant_is_forbidden(self):
        self.assertEqual(self.assistant_client.get(self.url).status_code, 403)

    def test_patient_of_another_cabinet_is_404(self):
        other = Cabinet.objects.create(nom="Autre", slug="autre")
        stranger = Patient.objects.create(cabinet=other, first_name="A", last_name="B")
        response = self.doctor_client.get(reverse("clinical:patient_file", args=[stranger.pk]))
        self.assertEqual(response.status_code, 404)

    def test_consultations_listed_most_recent_first(self):
        old = self._visit(60, "DIAG-ANCIENNE")
        recent = self._visit(2, "DIAG-RECENTE")
        middle = self._visit(20, "DIAG-MILIEU")
        html = self.doctor_client.get(self.url).content.decode()
        positions = [html.index(f'id="visite-{c.pk}"') for c in (recent, middle, old)]
        self.assertEqual(positions, sorted(positions))
        for text in ("DIAG-RECENTE", "DIAG-MILIEU", "DIAG-ANCIENNE", "Pénicilline", "G2P1"):
            self.assertIn(text, html)

    def test_page_without_consultation(self):
        response = self.doctor_client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aucune consultation pour le moment")

    def test_visit_card_shows_read_only_details_and_pdf_links(self):
        act = MedicalAct.objects.create(cabinet=self.cabinet, code="ECHO", name="Échographie obstétricale",
                                        price=Decimal("1100"), is_quick_exam=True)
        visit = self._visit(5, "Grossesse évolutive", weight_kg=Decimal("64"), height_cm=Decimal("160"),
                            blood_pressure="12/8", last_menstrual_period=timezone.localdate() - timedelta(days=12 * 7 + 3 + 5))
        ConsultationAct.objects.create(consultation=visit, act=act, price=act.price)
        Document.objects.create(consultation=visit, document_type=Document.DocumentType.PRESCRIPTION, content="Acide folique")
        Document.objects.create(consultation=visit, document_type=Document.DocumentType.CERTIFICATE, content="Certifie…")
        html = self.doctor_client.get(self.url).content.decode()
        self.assertIn("12 SA + 3 j", html)  # terme au jour de la visite
        self.assertIn("25,0", html)  # IMC
        self.assertIn("Acide folique", html)
        self.assertIn("1 100,00 DH", html)
        self.assertIn(reverse("clinical:prescription_pdf", args=[visit.appointment_id]), html)
        self.assertIn(reverse("clinical:report_pdf", args=[visit.appointment_id]), html)
        self.assertIn(reverse("clinical:letter_pdf", args=[visit.appointment_id, "certificate"]), html)
        self.assertNotIn(reverse("clinical:letter_pdf", args=[visit.appointment_id, "letter"]), html)
        self.assertNotIn("<textarea", html)  # lecture seule

    def test_entry_points_link_to_patient_file(self):
        visit = self._visit(1, "")
        Appointment.objects.filter(pk=visit.appointment_id).update(status=Appointment.Status.WAITING, date=timezone.now())

        doctor_list = self.doctor_client.get(reverse("patients:index")).content.decode()
        self.assertIn(self.url, doctor_list)
        assistant_list = self.assistant_client.get(reverse("patients:index")).content.decode()
        self.assertNotIn(self.url, assistant_list)
        self.assertIn(reverse("patients:edit_patient", args=[self.patient.pk]), assistant_list)

        self.assertIn(self.url, self.doctor_client.get(reverse("clinical:doctor_dashboard")).content.decode())

        current = Appointment.objects.create(cabinet=self.cabinet, patient=self.patient, date=timezone.now())
        cockpit = self.doctor_client.get(reverse("clinical:consultation_detail", args=[current.pk])).content.decode()
        self.assertIn("Voir le dossier complet", cockpit)
        self.assertIn(f"{self.url}#visite-{visit.pk}", cockpit)

    def test_upload_from_file_returns_to_documents_tab(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with self.settings(MEDIA_ROOT=media):
            self._upload_checks()

    def _upload_checks(self):
        response = self.doctor_client.post(
            reverse("patients:patient_documents", args=[self.patient.pk]),
            {"title": "Bilan", "document_type": "bilan", "file": SimpleUploadedFile("bilan.pdf", b"%PDF-1.4"),
             "next": f"{self.url}#documents"},
        )
        self.assertRedirects(response, f"{self.url}#documents", fetch_redirect_response=False)
        evil = self.doctor_client.post(
            reverse("patients:patient_documents", args=[self.patient.pk]),
            {"title": "X", "file": SimpleUploadedFile("x.pdf", b"%PDF-1.4"), "next": "https://evil.example/"},
        )
        self.assertRedirects(evil, reverse("patients:patient_documents", args=[self.patient.pk]), fetch_redirect_response=False)
