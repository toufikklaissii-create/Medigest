"""Historique des consultations dans la fiche de consultation (demande du Dr Errmili).

À la 2e visite on voit la 1re ; à la 3e on voit la 1re et la 2e, numérotées dans l'ordre
chronologique, avec leur contenu complet et leurs documents à réimprimer.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation, Document
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class ConsultationHistoryTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_hist", password="testpass123")
        Profile.objects.update_or_create(
            user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet}
        )
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Salma", last_name="Bennani")
        self.client = Client()
        self.client.login(username="dr_hist", password="testpass123")

    def _visit(self, days_ago, **fields):
        appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, reason="Suivi",
            date=timezone.now() - timedelta(days=days_ago), status=Appointment.Status.COMPLETED,
        )
        return Consultation.objects.create(
            appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor, **fields
        )

    def _page(self, consultation):
        url = reverse("clinical:consultation_detail", args=[consultation.appointment_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_first_visit_has_no_history_tab(self):
        first = self._visit(0)
        html = self._page(first)
        self.assertIn("Première consultation au cabinet.", html)
        self.assertNotIn('id="panel-historique"', html)
        self.assertNotIn('key: "historique"', html)

    def test_second_visit_shows_the_first_in_full(self):
        first = self._visit(30, clinical_exam="EXAMEN-V1", ultrasound_notes="ECHO-V1",
                            clinical_notes="OBS-V1", diagnostic="DIAG-V1", blood_pressure="11/7")
        Document.objects.create(consultation=first, document_type=Document.DocumentType.PRESCRIPTION,
                                content="Acide folique 0,4 mg")
        Document.objects.create(consultation=first, document_type=Document.DocumentType.BILAN_BIOLOGIQUE,
                                content="NFS")
        Document.objects.create(consultation=first, document_type=Document.DocumentType.CERT_GROSSESSE,
                                content="Certifie que Mme…")
        second = self._visit(0)
        html = self._page(second)
        self.assertIn('id="panel-historique"', html)
        self.assertIn('key: "historique", label: "Historique (1)"', html)
        self.assertIn("Consultation 1", html)
        # Contenu complet, pas un résumé tronqué.
        for text in ("EXAMEN-V1", "ECHO-V1", "OBS-V1", "DIAG-V1", "11/7", "Acide folique 0,4 mg", "NFS"):
            self.assertIn(text, html)
        # Documents de la visite précédente à réimprimer.
        self.assertIn(reverse("clinical:prescription_pdf", args=[first.appointment_id]), html)
        self.assertIn(reverse("clinical:prescription_part_pdf", args=[first.appointment_id, "bilan"]), html)
        self.assertIn(reverse("clinical:letter_pdf", args=[first.appointment_id, "cert_grossesse"]), html)
        # La consultation en cours n'apparaît pas dans son propre historique.
        self.assertNotIn(f'id="visite-{second.pk}"', html)

    def test_third_visit_shows_first_and_second_numbered_most_recent_first(self):
        first = self._visit(60, diagnostic="DIAG-V1")
        second = self._visit(30, diagnostic="DIAG-V2")
        third = self._visit(0)
        html = self._page(third)
        self.assertIn('label: "Historique (2)"', html)
        self.assertLess(html.index(f'id="visite-{second.pk}"'), html.index(f'id="visite-{first.pk}"'))
        self.assertIn("DIAG-V1", html)
        self.assertIn("DIAG-V2", html)
        # Numérotation chronologique : la 1re visite est « Consultation 1 ».
        card_v1 = html[html.index(f'id="visite-{first.pk}"'):]
        card_v2 = html[html.index(f'id="visite-{second.pk}"'):html.index(f'id="visite-{first.pk}"')]
        self.assertIn("Consultation 1", card_v1[:3000])
        self.assertIn("Consultation 2", card_v2)
        # Barre latérale : chaque visite ouvre l'onglet Historique.
        self.assertIn(f"showVisit({first.pk})", html)
        self.assertIn(f"showVisit({second.pk})", html)

    def test_more_than_three_visits_are_all_listed(self):
        visits = [self._visit(100 - 10 * i, diagnostic=f"DIAG-{i}") for i in range(5)]
        current = self._visit(0)
        html = self._page(current)
        self.assertIn('label: "Historique (5)"', html)
        for visit in visits:
            self.assertIn(f'id="visite-{visit.pk}"', html)

    def test_history_is_limited_to_the_patient_and_cabinet(self):
        other_patient = Patient.objects.create(cabinet=self.cabinet, first_name="Autre", last_name="Patiente")
        appt = Appointment.objects.create(cabinet=self.cabinet, patient=other_patient, reason="Suivi",
                                          date=timezone.now() - timedelta(days=10),
                                          status=Appointment.Status.COMPLETED)
        Consultation.objects.create(appointment=appt, patient=other_patient, cabinet=self.cabinet,
                                    doctor=self.doctor, diagnostic="DIAG-AUTRE-PATIENTE")
        current = self._visit(0)
        html = self._page(current)
        self.assertNotIn("DIAG-AUTRE-PATIENTE", html)
        self.assertNotIn('id="panel-historique"', html)

    def test_patient_file_numbers_visits_too(self):
        self._visit(30, diagnostic="DIAG-V1")
        self._visit(5, diagnostic="DIAG-V2")
        html = self.client.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn("Consultation 1", html)
        self.assertIn("Consultation 2", html)
