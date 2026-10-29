"""Rôle « Médecin remplaçant » : tout le clinique, rien de ce qui touche à l'argent.

Le cloisonnement est vérifié côté serveur (URL tapées à la main, code source des pages),
pas seulement dans les menus.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct, Payment
from apps.clinical.models import Consultation, ConsultationAct, Document
from apps.clinical.services import doctor_display_name
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class RemplacantBase(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-rempl")
        self.doctor = User.objects.create_user(username="dr_titulaire", password="x",
                                               first_name="Khadija", last_name="Errmili")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.remplacant = User.objects.create_user(username="dr_rempl", password="x",
                                                   first_name="Youssef", last_name="Fictif")
        Profile.objects.update_or_create(
            user=self.remplacant, defaults={"role": Profile.Role.REMPLACANT, "cabinet": self.cabinet}
        )
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Salma", last_name="Fictive")
        self.act = MedicalAct.objects.create(cabinet=self.cabinet, code="CONS", name="Consultation gynécologique",
                                             price=Decimal("437"))
        self.libre = MedicalAct.objects.create(cabinet=self.cabinet, code="ECHO", name="Échographie",
                                               price=Decimal("0"), prix_libre=True)
        self.client = Client()
        self.client.force_login(self.remplacant)
        self.doctor_client = Client()
        self.doctor_client.force_login(self.doctor)

    def appointment(self, days_ago=0):
        return Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, reason="Suivi",
            date=timezone.now() - timedelta(days=days_ago), status=Appointment.Status.IN_CONSULTATION,
        )


class RemplacantMoneyAccessTest(RemplacantBase):
    def test_pages_argent_refusees(self):
        invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("437"))
        urls = [
            reverse("billing:index"),
            reverse("billing:reports"),
            reverse("billing:daily_revenue"),
            reverse("billing:cash_register"),
            reverse("billing:tariffs"),
            reverse("billing:export_xlsx"),
            reverse("billing:export_pdf"),
            reverse("billing:invoice_pdf", args=[invoice.pk]),
            reverse("billing:pay_invoice", args=[invoice.pk]),
            reverse("billing:pending_invoices"),
            reverse("appointments:assistant_dashboard"),
            reverse("appointments:reception_timeline"),
            reverse("accounts:settings"),
            reverse("accounts:remplacants"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        # Écritures aussi refusées.
        self.assertEqual(self.client.post(reverse("billing:pay_invoice", args=[invoice.pk]),
                                          {"amount": "437", "method": "cash"}).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_menu_sans_argent(self):
        html = self.client.get(reverse("clinical:doctor_dashboard")).content.decode()
        for label in ("Facturation", "Recettes du jour", "Rapports", "Caisse", "Tarifs", "Réglages du cabinet"):
            self.assertNotIn(f">{label}</span>", html)
        for label in ("Accueil", "Planning", "Patientes", "Modèles"):
            self.assertIn(f">{label}</span>", html)

    def test_connexion_mene_au_tableau_medical(self):
        response = self.client.get(reverse("accounts:post_login_redirect"))
        self.assertRedirects(response, reverse("clinical:doctor_dashboard"), fetch_redirect_response=False)

    def test_archives_facture_refusees(self):
        path = f"documents/{self.cabinet.pk}/{self.patient.patient_number}/2026-10-20/facture_F-1_101010.pdf"
        response = self.client.get(f"/media/{path}")
        self.assertEqual(response.status_code, 403)


class RemplacantClinicalAccessTest(RemplacantBase):
    def test_pages_cliniques_accessibles(self):
        appointment = self.appointment()
        urls = [
            reverse("clinical:doctor_dashboard"),
            reverse("clinical:consultation_detail", args=[appointment.pk]),
            reverse("clinical:patient_file", args=[self.patient.pk]),
            reverse("clinical:modeles_ordonnance"),
            reverse("clinical:modeles_courrier"),
            reverse("patients:index"),
            reverse("appointments:calendar"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_consultation_sans_aucun_montant(self):
        appointment = self.appointment()
        html = self.client.get(reverse("clinical:consultation_detail", args=[appointment.pk])).content.decode()
        self.assertIn("Actes réalisés", html)
        self.assertIn("Consultation gynécologique", html)
        self.assertNotIn("437", html)  # tarif absent, même du code source
        self.assertNotIn('name="billing_discount"', html)
        self.assertNotIn('name="billing_free"', html)
        self.assertNotIn(f'name="price_{self.act.pk}"', html)
        self.assertIn(f'name="price_{self.libre.pk}"', html)  # prix libre : seul montant saisissable

    def test_post_ignore_prix_remise_et_gratuite(self):
        appointment = self.appointment()
        url = reverse("clinical:consultation_detail", args=[appointment.pk])
        self.client.post(url, {
            "action": "validate", "acts": [self.act.pk], f"price_{self.act.pk}": "1",
            "billing_discount": "400", "billing_free": "on", "diagnostic": "RAS",
        })
        consultation = Consultation.objects.get(appointment=appointment)
        self.assertEqual(consultation.status, Consultation.Status.VALIDATED)
        self.assertEqual(consultation.consultation_acts.get().price, Decimal("437"))  # tarif du catalogue
        self.assertEqual(consultation.billing_discount, 0)
        self.assertFalse(consultation.billing_free)
        self.assertEqual(consultation.invoice.total_amount, Decimal("437"))  # facture faite pour l'assistante

    def test_prix_libre_saisi_par_le_remplacant(self):
        appointment = self.appointment()
        url = reverse("clinical:consultation_detail", args=[appointment.pk])
        self.client.post(url, {"action": "validate", "acts": [self.libre.pk], f"price_{self.libre.pk}": "250"})
        consultation = Consultation.objects.get(appointment=appointment)
        self.assertEqual(consultation.consultation_acts.get().price, Decimal("250"))

    def test_remplacant_signe_les_documents(self):
        appointment = self.appointment()
        # Constantes saisies par l'assistante : consultation créée au nom de la doctoresse.
        Consultation.objects.create(appointment=appointment, patient=self.patient, cabinet=self.cabinet,
                                    doctor=self.doctor)
        self.client.post(reverse("clinical:consultation_detail", args=[appointment.pk]),
                         {"action": "draft", "diagnostic": "RAS"})
        consultation = Consultation.objects.get(appointment=appointment)
        self.assertEqual(consultation.doctor, self.remplacant)
        self.assertEqual(doctor_display_name(User.objects.get(pk=self.remplacant.pk)), "Dr Youssef Fictif (remplaçant)")
        self.assertEqual(doctor_display_name(User.objects.get(pk=self.doctor.pk)), "Dr Khadija Errmili")

    def test_dossier_patiente_sans_factures_ni_prix(self):
        old = self.appointment(days_ago=10)
        consultation = Consultation.objects.create(appointment=old, patient=self.patient, cabinet=self.cabinet,
                                                   doctor=self.doctor, diagnostic="DIAG-ANCIEN")
        ConsultationAct.objects.create(consultation=consultation, act=self.act, price=Decimal("437"))
        Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("437"),
                               invoice_number="FACT-TEST-1")
        Document.objects.create(consultation=consultation, document_type=Document.DocumentType.PRESCRIPTION,
                                content="Fer")
        html = self.client.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn("DIAG-ANCIEN", html)
        self.assertNotIn("FACT-TEST-1", html)
        self.assertNotIn("437", html)
        self.assertNotIn('id="panel-factures"', html)
        # La doctoresse, elle, voit tout.
        doctor_html = self.doctor_client.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn("FACT-TEST-1", doctor_html)

    def test_historique_sans_prix_dans_la_consultation(self):
        old = self.appointment(days_ago=10)
        consultation = Consultation.objects.create(appointment=old, patient=self.patient, cabinet=self.cabinet,
                                                   doctor=self.doctor, diagnostic="DIAG-ANCIEN")
        ConsultationAct.objects.create(consultation=consultation, act=self.act, price=Decimal("437"))
        current = self.appointment()
        html = self.client.get(reverse("clinical:consultation_detail", args=[current.pk])).content.decode()
        self.assertIn("DIAG-ANCIEN", html)
        self.assertNotIn("437", html)


@override_settings(ALLOWED_HOSTS=["testserver"])
class GestionRemplacantsTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-gestion")
        self.doctor = User.objects.create_user(username="dr_gestion", password="x")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_gestion", password="x")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.client = Client()
        self.client.force_login(self.doctor)
        self.url = reverse("accounts:remplacants")

    def _create(self, **extra):
        data = {"first_name": "Youssef", "last_name": "Fictif", "password": "Remplacant-2026!",
                "password2": "Remplacant-2026!", **extra}
        return self.client.post(self.url, data)

    def test_creation_compte(self):
        response = self._create()
        self.assertRedirects(response, self.url)
        user = User.objects.get(first_name="Youssef")
        self.assertEqual(user.username, "dr_fictif")
        self.assertEqual(user.profile.role, Profile.Role.REMPLACANT)
        self.assertEqual(user.profile.cabinet, self.cabinet)
        self.assertTrue(user.check_password("Remplacant-2026!"))
        self.assertTrue(Client().login(username="dr_fictif", password="Remplacant-2026!"))

    def test_mots_de_passe_differents_ou_trop_simples(self):
        self._create(password2="autre")
        self._create(password="123", password2="123")
        self.assertFalse(User.objects.filter(first_name="Youssef").exists())

    def test_identifiant_deja_pris(self):
        response = self._create(username="dr_gestion")
        self.assertContains(response, "déjà utilisé")

    def test_desactivation_bloque_la_connexion(self):
        self._create()
        user = User.objects.get(first_name="Youssef")
        session = Client()
        session.force_login(user)
        self.client.post(reverse("accounts:remplacant_toggle", args=[user.pk]))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(Client().login(username="dr_fictif", password="Remplacant-2026!"))
        # Session ouverte : déconnectée à la requête suivante.
        response = session.get(reverse("clinical:doctor_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.client.post(reverse("accounts:remplacant_toggle", args=[user.pk]))
        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_nouveau_mot_de_passe(self):
        self._create()
        user = User.objects.get(first_name="Youssef")
        self.client.post(reverse("accounts:remplacant_password", args=[user.pk]),
                         {"password": "Nouveau-Mdp-2026", "password2": "Nouveau-Mdp-2026"})
        user.refresh_from_db()
        self.assertTrue(user.check_password("Nouveau-Mdp-2026"))

    def test_seule_la_doctoresse_gere_les_comptes(self):
        self._create()
        user = User.objects.get(first_name="Youssef")
        assistant = Client()
        assistant.force_login(self.assistant)
        self.assertEqual(assistant.get(self.url).status_code, 403)
        self.assertEqual(assistant.post(reverse("accounts:remplacant_toggle", args=[user.pk])).status_code, 403)

    def test_ne_touche_pas_aux_autres_comptes(self):
        # La doctoresse ne peut pas désactiver l'assistante ni un compte d'un autre cabinet par cette page.
        response = self.client.post(reverse("accounts:remplacant_toggle", args=[self.assistant.pk]))
        self.assertEqual(response.status_code, 404)
        self.assistant.refresh_from_db()
        self.assertTrue(self.assistant.is_active)

    def test_lien_depuis_les_reglages(self):
        html = self.client.get(reverse("accounts:settings")).content.decode()
        self.assertIn(self.url, html)
