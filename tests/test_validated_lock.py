from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.branding import _hex_to_rgb, _relative_luminance, brand_scale, contrast_with_white
from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.clinical.models import Consultation, ConsultationAct
from apps.patients.models import Patient


def _contrast(a, b):
    la, lb = (_relative_luminance(_hex_to_rgb(c)) for c in (a, b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class RosePoudrePaletteTest(SimpleTestCase):
    def test_palette_is_soft_and_aa(self):
        scale = brand_scale("#B84A6E")
        for step in (600, 700):  # boutons primaires, texte blanc
            self.assertGreaterEqual(contrast_with_white(scale[step]), 4.5, step)
        for step in (600, 700):  # liens / texte de marque sur fonds pâles
            for background in (scale[25], scale[50], "#FFFFFF"):
                self.assertGreaterEqual(_contrast(scale[step], background), 4.5, (step, background))
        self.assertLess(contrast_with_white(scale[25]), 1.06)  # fond rose très pâle
        # Sidebar : prune très foncé, texte clair largement lisible.
        for step in (900, 950):
            self.assertGreaterEqual(contrast_with_white(scale[step]), 12, step)
            r, g, b = _hex_to_rgb(scale[step])
            self.assertTrue(r > g and b > g, scale[step])  # prune : rouge et bleu au-dessus du vert


@override_settings(ALLOWED_HOSTS=["testserver"])
class ValidatedConsultationLockTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_lock", password="testpass123")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="Meryem", last_name="Tazi")
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=patient, date=timezone.now() - timedelta(minutes=30),
            status=Appointment.Status.COMPLETED,
        )
        self.consult_act = MedicalAct.objects.create(cabinet=self.cabinet, code="CONS", name="Consultation", price=Decimal("300"))
        self.echo_act = MedicalAct.objects.create(cabinet=self.cabinet, code="ECHO", name="Échographie", price=Decimal("500"))
        self.consultation = Consultation.objects.create(
            appointment=self.appt, patient=patient, cabinet=self.cabinet, doctor=self.doctor,
            diagnostic="Diagnostic initial",
        )
        ConsultationAct.objects.create(consultation=self.consultation, act=self.consult_act, price=self.consult_act.price)
        self.consultation.status = Consultation.Status.VALIDATED
        self.consultation.save()  # → facture en attente de 300 DH
        self.client = Client()
        self.client.login(username="dr_lock", password="testpass123")
        self.url = reverse("clinical:consultation_detail", args=[self.appt.pk])

    def test_validated_cockpit_is_read_only(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Modifier la consultation", html)
        self.assertIn("lecture seule", html)
        self.assertNotIn("Valider la consultation", html)
        self.assertNotIn(reverse("clinical:autosave_consultation", args=[self.appt.pk]), html)
        self.assertIn('disabled aria-describedby="locked-note"', html)
        self.assertIn(reverse("clinical:unlock_consultation", args=[self.appt.pk]), html)

    def test_validated_consultation_cannot_be_modified_without_unlock(self):
        self.client.post(self.url, {"action": "validate", "diagnostic": "Réécrit", "acts": [self.echo_act.pk]})
        self.consultation.refresh_from_db()
        self.assertEqual(self.consultation.diagnostic, "Diagnostic initial")
        self.assertEqual(self.consultation.consultation_acts.count(), 1)
        autosave = self.client.post(reverse("clinical:autosave_consultation", args=[self.appt.pk]), {"diagnostic": "X"})
        self.assertEqual(autosave.status_code, 409)

    def test_unlock_then_edit_and_revalidate(self):
        self.client.post(reverse("clinical:unlock_consultation", args=[self.appt.pk]))
        self.consultation.refresh_from_db()
        self.assertEqual(self.consultation.status, Consultation.Status.DRAFT)
        self.assertIn("Valider la consultation", self.client.get(self.url).content.decode())

        self.client.post(self.url, {
            "action": "validate", "diagnostic": "Complété",
            "acts": [self.consult_act.pk, self.echo_act.pk],
        })
        self.consultation.refresh_from_db()
        self.assertEqual(self.consultation.diagnostic, "Complété")
        self.assertEqual(self.consultation.invoice.total_amount, Decimal("800"))

    def test_unlock_never_rewrites_a_paid_invoice(self):
        invoice = self.consultation.invoice
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.PAID, payment_method="cash")
        self.client.post(reverse("clinical:unlock_consultation", args=[self.appt.pk]))
        self.client.post(self.url, {"action": "validate", "acts": [self.consult_act.pk, self.echo_act.pk]})
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.total_amount, Decimal("300"))

    def test_unlock_requires_post(self):
        self.assertEqual(self.client.get(reverse("clinical:unlock_consultation", args=[self.appt.pk])).status_code, 405)
