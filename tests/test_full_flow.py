from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.clinical.models import Consultation
from apps.communications.models import Task
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class FullClinicJourneyTest(TestCase):
    """End-to-end regression test: Connexion -> Patiente -> RDV -> Consultation
    -> Actes -> Ordonnance PDF -> Encaissement -> Reçu PDF -> Tâches."""

    def setUp(self):
        self.doctor = User.objects.create_user(username="dr_test", password="testpass123")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR})

        self.assistant = User.objects.create_user(username="assist_test", password="testpass123")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT}
        )

        self.act_consultation = MedicalAct.objects.create(
            code="CONS_TEST", name="Consultation test", price=300
        )
        self.act_echo = MedicalAct.objects.create(code="ECHO_TEST", name="Écho test", price=500)

        self.assistant_client = Client()
        self.doctor_client = Client()

    def test_full_patient_journey(self):
        # 1. Connexion — l'assistante se connecte et est redirigée vers son tableau de bord
        self.assertTrue(
            self.assistant_client.login(username="assist_test", password="testpass123")
        )
        response = self.assistant_client.get(reverse("accounts:post_login_redirect"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse("appointments:assistant_dashboard"))

        self.assertTrue(self.doctor_client.login(username="dr_test", password="testpass123"))
        response = self.doctor_client.get(reverse("accounts:post_login_redirect"), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse("clinical:doctor_dashboard"))

        # Un médecin ne peut jamais accéder au tableau de bord assistante ? (autorisé,
        # seule la zone clinique est verrouillée) — vérifié séparément plus bas.

        # 2. Création patiente par l'assistante
        response = self.assistant_client.post(
            reverse("patients:create_patient"),
            {
                "first_name": "Fatima",
                "last_name": "Testaoui",
                "cin": "TT123456",
                "phone": "0600000000",
                "allergies": "Pénicilline",
                "medical_history": "RAS",
            },
        )
        self.assertEqual(response.status_code, 302)
        patient = Patient.objects.get(cin="TT123456")
        self.assertTrue(patient.patient_number.startswith("PAT-"))

        # 3. Prise de RDV pour cette patiente
        response = self.assistant_client.post(
            reverse("appointments:create_appointment_for", args=[patient.pk]),
            {"date": "2026-09-01T10:00", "duration_minutes": "30", "reason": "Consultation de suivi"},
        )
        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get(patient=patient)
        self.assertEqual(appointment.status, Appointment.Status.SCHEDULED)

        # Assistante fait progresser la file jusqu'à "en consultation"
        for _ in range(3):
            response = self.assistant_client.post(
                reverse("appointments:advance_status", args=[appointment.pk])
            )
            self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.IN_CONSULTATION)

        # Une assistante ne peut jamais accéder aux URLs cliniques
        response = self.assistant_client.get(reverse("clinical:doctor_dashboard"))
        self.assertEqual(response.status_code, 403)

        # 4. Consultation médecin : accès à la fiche
        response = self.doctor_client.get(
            reverse("clinical:consultation_detail", args=[appointment.pk])
        )
        self.assertEqual(response.status_code, 200)
        consultation = Consultation.objects.get(appointment=appointment)

        # 5. Actes réalisés + validation -> facture auto-générée
        response = self.doctor_client.post(
            reverse("clinical:consultation_detail", args=[appointment.pk]),
            {
                "action": "validate",
                "blood_pressure": "12/8",
                "weight_kg": "62",
                "clinical_notes": "Examen sans particularité.",
                "diagnostic": "Suivi normal.",
                "last_menstrual_period": "2026-06-01",
                "gestational_age_weeks": "12",
                "ultrasound_notes": "BIP 45mm, LF 30mm",
                "prescription_content": "Acide folique 0,4 mg — 1 comprimé par jour",
                "acts": [str(self.act_consultation.pk), str(self.act_echo.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        consultation.refresh_from_db()
        self.assertEqual(consultation.status, Consultation.Status.VALIDATED)
        self.assertIsNotNone(consultation.invoice)
        invoice = consultation.invoice
        self.assertEqual(invoice.total_amount, 800)
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.COMPLETED)

        # 6. Téléchargement de l'ordonnance PDF
        response = self.doctor_client.get(
            reverse("clinical:prescription_pdf", args=[appointment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

        # Une assistante ne peut pas non plus télécharger un document clinique
        response = self.assistant_client.get(
            reverse("clinical:prescription_pdf", args=[appointment.pk])
        )
        self.assertEqual(response.status_code, 403)

        # 7. Encaissement par l'assistante
        response = self.assistant_client.post(
            reverse("billing:pay_invoice", args=[invoice.pk]), {"payment_method": "cash"}
        )
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.payment_method, "cash")
        self.assertIsNotNone(invoice.paid_at)

        # 8. Téléchargement du reçu PDF
        response = self.assistant_client.get(reverse("billing:invoice_receipt", args=[invoice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

        # 9. Tâches — le médecin envoie une consigne, l'assistante la termine
        response = self.doctor_client.post(
            reverse("communications:create_task"),
            {
                "title": "Rappeler la patiente pour résultat frottis",
                "description": "Résultats attendus sous 48h",
                "patient": str(patient.pk),
                "priority": "urgent",
            },
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(patient=patient)
        self.assertEqual(task.assignee, self.assistant)
        self.assertEqual(task.status, Task.Status.PENDING)

        response = self.assistant_client.get(reverse("communications:tasks_panel"))
        self.assertContains(response, "Rappeler la patiente")

        response = self.assistant_client.post(reverse("communications:toggle_task", args=[task.pk]))
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertEqual(task.status, Task.Status.COMPLETED)

        response = self.assistant_client.get(reverse("communications:tasks_panel"))
        self.assertNotContains(response, "Rappeler la patiente")
