import importlib
import io
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.amount_words import montant_en_lettres
from apps.billing.models import Invoice, InvoiceItem, MedicalAct, Payment
from apps.billing.services import generate_invoice_pdf, record_payment
from apps.clinical.models import Consultation
from apps.communications.models import Task
from apps.patients.models import Patient


class AmountInWordsTest(SimpleTestCase):
    def test_french_amounts(self):
        cases = {
            "0": "zéro dirham",
            "1": "un dirham",
            "21": "vingt et un dirhams",
            "71": "soixante et onze dirhams",
            "80": "quatre-vingts dirhams",
            "91": "quatre-vingt-onze dirhams",
            "100": "cent dirhams",
            "200": "deux cents dirhams",
            "350": "trois cent cinquante dirhams",
            "1000": "mille dirhams",
            "1250.50": "mille deux cent cinquante dirhams et cinquante centimes",
        }
        for amount, expected in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(montant_en_lettres(Decimal(amount)), expected)

    def test_hundreds_and_thousands_agreement(self):
        self.assertEqual(montant_en_lettres(Decimal("280000")), "deux cent quatre-vingt mille dirhams")
        self.assertEqual(montant_en_lettres(Decimal("201")), "deux cent un dirhams")
        self.assertEqual(montant_en_lettres(Decimal("0.01")), "zéro dirham et un centime")


@override_settings(ALLOWED_HOSTS=["testserver"])
class BillingTestBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-billing")
        self.doctor = User.objects.create_user(username="dr_bill", password="x")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_bill", password="x")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Nadia", last_name="Alaoui")
        self.consult = MedicalAct.objects.create(cabinet=self.cabinet, code="CONS", name="Consultation", price=Decimal("300"))
        self.echo = MedicalAct.objects.create(cabinet=self.cabinet, code="ECHO", name="Échographie", price=Decimal("200"))

        self.doctor_client = Client()
        self.doctor_client.force_login(self.doctor)
        self.assistant_client = Client()
        self.assistant_client.force_login(self.assistant)

    def _appointment(self):
        return Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(),
            status=Appointment.Status.IN_CONSULTATION,
        )

    def _validate(self, appointment, **post):
        data = {"action": "validate", "acts": [str(self.consult.pk), str(self.echo.pk)], **post}
        response = self.doctor_client.post(reverse("clinical:consultation_detail", args=[appointment.pk]), data)
        self.assertEqual(response.status_code, 302)
        return Consultation.objects.get(appointment=appointment).invoice

    def _invoice(self, total="500"):
        invoice = Invoice.objects.create(cabinet=self.cabinet, patient=self.patient, total_amount=Decimal(total))
        InvoiceItem.objects.create(invoice=invoice, act=self.consult, price=Decimal(total))
        return invoice

    def _pay(self, invoice, client=None, **data):
        return (client or self.assistant_client).post(
            reverse("billing:pay_invoice", args=[invoice.pk]), data, HTTP_HX_REQUEST="true"
        )


class DoctorAmountsTest(BillingTestBase):
    def test_line_price_and_discount_applied_at_validation(self):
        invoice = self._validate(
            self._appointment(),
            **{f"price_{self.consult.pk}": "250", "billing_discount": "50"},
        )
        self.assertEqual(
            sorted(invoice.items.values_list("price", flat=True)), [Decimal("200"), Decimal("250")]
        )
        self.assertEqual(invoice.discount, Decimal("50"))
        self.assertEqual(invoice.total_amount, Decimal("400"))
        self.assertEqual(invoice.status, Invoice.Status.PENDING)
        # Le catalogue n'est pas touché par un prix de ligne.
        self.consult.refresh_from_db()
        self.assertEqual(self.consult.price, Decimal("300"))

    def test_discount_is_capped_at_subtotal(self):
        invoice = self._validate(self._appointment(), billing_discount="9999")
        self.assertEqual(invoice.total_amount, Decimal("0"))
        self.assertEqual(invoice.discount, Decimal("500"))

    def test_free_control_keeps_a_traced_zero_invoice(self):
        invoice = self._validate(self._appointment(), billing_free="on")
        self.assertTrue(invoice.invoice_number.startswith("FAC-"))
        self.assertTrue(invoice.is_free)
        self.assertEqual(invoice.total_amount, Decimal("0"))
        self.assertEqual(invoice.items.count(), 2)
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0"))

    def test_autosave_stores_prices_discount_and_free(self):
        appointment = self._appointment()
        self.doctor_client.get(reverse("clinical:consultation_detail", args=[appointment.pk]))
        response = self.doctor_client.post(
            reverse("clinical:autosave_consultation", args=[appointment.pk]),
            {"acts": [str(self.consult.pk)], f"price_{self.consult.pk}": "275,50", "billing_discount": "25", "billing_free": "on"},
        )
        self.assertEqual(response.status_code, 204)
        consultation = Consultation.objects.get(appointment=appointment)
        self.assertEqual(consultation.consultation_acts.get().price, Decimal("275.50"))
        self.assertEqual(consultation.billing_discount, Decimal("25"))
        self.assertTrue(consultation.billing_free)

    def test_paid_invoice_never_changes_on_revalidation(self):
        appointment = self._appointment()
        invoice = self._validate(appointment)
        record_payment(invoice, Decimal("100"), "cash", self.assistant)
        self.doctor_client.post(reverse("clinical:unlock_consultation", args=[appointment.pk]))
        self._validate(appointment, **{f"price_{self.consult.pk}": "999", "billing_discount": "10"})
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal("500"))
        self.assertEqual(invoice.discount, Decimal("0"))
        self.assertEqual(invoice.status, Invoice.Status.PARTIAL)


class AssistantCannotChangeAmountsTest(BillingTestBase):
    def test_assistant_gets_403_on_every_amount_endpoint(self):
        appointment = self._appointment()
        responses = [
            self.assistant_client.post(reverse("billing:tariff_row", args=[self.consult.pk]),
                                       {"code": "CONS", "name": "Consultation", "price": "1", "is_active": "on"}),
            self.assistant_client.post(reverse("billing:tariff_add"), {"code": "X", "name": "X", "price": "1"}),
            self.assistant_client.post(reverse("clinical:autosave_consultation", args=[appointment.pk]),
                                       {"acts": [str(self.consult.pk)], f"price_{self.consult.pk}": "1"}),
            self.assistant_client.post(reverse("clinical:consultation_detail", args=[appointment.pk]),
                                       {"action": "validate", "billing_discount": "500"}),
            self.assistant_client.get(reverse("billing:tariffs")),
        ]
        for response in responses:
            self.assertEqual(response.status_code, 403)
        self.consult.refresh_from_db()
        self.assertEqual(self.consult.price, Decimal("300"))
        self.assertFalse(MedicalAct.objects.filter(code="X").exists())
        self.assertFalse(Consultation.objects.filter(appointment=appointment).exists())

    def test_payment_post_cannot_rewrite_invoice_amount(self):
        invoice = self._invoice("500")
        self._pay(invoice, amount="100", payment_method="cash", total_amount="1", discount="400")
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal("500"))
        self.assertEqual(invoice.discount, Decimal("0"))
        self.assertEqual(invoice.balance_due, Decimal("400"))


class PaymentsTest(BillingTestBase):
    def test_modal_prefills_balance_due(self):
        invoice = self._invoice("500")
        record_payment(invoice, Decimal("150"), "cash", self.assistant)
        html = self.assistant_client.get(reverse("billing:pay_invoice", args=[invoice.pk])).content.decode()
        self.assertIn('value="350,00"', html)
        self.assertIn("Signaler un écart", html)

    def test_partial_then_settle(self):
        invoice = self._invoice("500")
        response = self._pay(invoice, amount="200", payment_method="cash")
        self.assertIn("invoice-paid", response["HX-Trigger"])
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIAL)
        self.assertEqual(invoice.amount_paid, Decimal("200"))
        self.assertEqual(invoice.balance_due, Decimal("300"))

        self._pay(invoice, amount="300", payment_method="check", reference="CHQ-0042")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(invoice.balance_due, Decimal("0"))
        payments = list(invoice.payments.all())
        self.assertEqual(len(payments), 2)
        self.assertEqual(payments[1].reference, "CHQ-0042")
        self.assertEqual(payments[1].received_by, self.assistant)
        # paid_at / mode = dernier paiement
        self.assertEqual(invoice.paid_at, payments[1].paid_at)
        self.assertEqual(invoice.payment_method, "check")

    def test_overpayment_refused(self):
        invoice = self._invoice("500")
        response = self._pay(invoice, amount="500,01", payment_method="cash")
        self.assertEqual(response.status_code, 200)
        self.assertIn("dépasse le reste dû", response.content.decode())
        self.assertFalse(Payment.objects.exists())
        record_payment(invoice, None, "card", self.assistant)
        response = self._pay(invoice, amount="1", payment_method="cash")
        self.assertIn("déjà soldée", response.content.decode())
        self.assertEqual(Payment.objects.count(), 1)

    def test_reference_required_for_check_and_transfer(self):
        invoice = self._invoice("500")
        for method in ("check", "transfer"):
            response = self._pay(invoice, amount="100", payment_method=method, reference="  ")
            self.assertIn("Indiquez le numéro", response.content.decode())
        self.assertFalse(Payment.objects.exists())

    def test_revenue_counts_on_payment_date(self):
        invoice = self._invoice("500")
        record_payment(invoice, Decimal("200"), "cash", self.assistant, paid_at=timezone.now() - timedelta(days=1))
        record_payment(invoice, Decimal("120"), "cash", self.assistant)
        response = self.doctor_client.get(reverse("billing:daily_revenue"))
        self.assertEqual(response.context["total"], Decimal("120"))
        response = self.assistant_client.get(reverse("appointments:assistant_dashboard"))
        self.assertNotIn("cashed_today", response.context)

    def test_receipt_per_payment(self):
        invoice = self._invoice("500")
        first = record_payment(invoice, Decimal("200"), "cash", self.assistant)
        second = record_payment(invoice, Decimal("300"), "card", self.assistant)
        self.assertEqual(first.receipt_number, f"{invoice.invoice_number}-1")
        self.assertEqual(second.receipt_number, f"{invoice.invoice_number}-2")
        response = self.assistant_client.get(reverse("billing:payment_receipt", args=[first.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_report_discrepancy_creates_task_for_doctor(self):
        invoice = self._invoice("500")
        response = self.assistant_client.post(
            reverse("billing:report_discrepancy", args=[invoice.pk]),
            {"message": "La patiente annonce 400 DH convenus."}, HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        task = Task.objects.get()
        self.assertEqual(task.assignee, self.doctor)
        self.assertEqual(task.author, self.assistant)
        self.assertIn(invoice.invoice_number, task.title)
        self.assertIn("400 DH convenus", task.description)
        invoice.refresh_from_db()
        self.assertEqual(invoice.total_amount, Decimal("500"))


class CancellationTest(BillingTestBase):
    def test_only_doctor_cancels_and_number_is_kept(self):
        invoice = self._invoice("500")
        number = invoice.invoice_number
        url = reverse("billing:cancel_invoice", args=[invoice.pk])

        self.assertEqual(self.assistant_client.post(url, {"reason": "Erreur"}).status_code, 403)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

        self.doctor_client.post(url, {"reason": ""}, HTTP_HX_REQUEST="true")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PENDING)

        self.doctor_client.post(url, {"reason": "Consultation non réalisée"}, HTTP_HX_REQUEST="true")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.CANCELLED)
        self.assertEqual(invoice.invoice_number, number)
        self.assertEqual(invoice.cancel_reason, "Consultation non réalisée")
        self.assertEqual(invoice.cancelled_by, self.doctor)
        self.assertIsNotNone(invoice.cancelled_at)
        self.assertEqual(invoice.balance_due, Decimal("0"))

        # Le numéro n'est jamais réattribué.
        self.assertNotEqual(self._invoice().invoice_number, number)
        self.assertEqual(Invoice.objects.filter(invoice_number=number).count(), 1)
        # Plus aucun encaissement possible.
        self.assertIn("annulée", self._pay(invoice, payment_method="cash").content.decode())

    def test_cashed_invoice_cannot_be_cancelled(self):
        invoice = self._invoice("500")
        record_payment(invoice, Decimal("100"), "cash", self.assistant)
        self.doctor_client.post(reverse("billing:cancel_invoice", args=[invoice.pk]), {"reason": "x"}, HTTP_HX_REQUEST="true")
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PARTIAL)

    def test_revalidating_after_cancellation_issues_new_invoice(self):
        appointment = self._appointment()
        invoice = self._validate(appointment)
        self.doctor_client.post(reverse("billing:cancel_invoice", args=[invoice.pk]), {"reason": "Erreur d'actes"})
        self.doctor_client.post(reverse("clinical:unlock_consultation", args=[appointment.pk]))
        new_invoice = self._validate(appointment)
        self.assertNotEqual(new_invoice.pk, invoice.pk)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.CANCELLED)


class BillingPagesTest(BillingTestBase):
    def test_filters_and_search(self):
        pending = self._invoice("500")
        paid = self._invoice("300")
        record_payment(paid, None, "cash", self.assistant)
        other = Patient.objects.create(cabinet=self.cabinet, first_name="Samira", last_name="Fassi")
        Invoice.objects.create(cabinet=self.cabinet, patient=other, total_amount=Decimal("100"))

        url = reverse("billing:index")
        response = self.doctor_client.get(url, {"statut": "paid"})
        self.assertEqual(list(response.context["invoices"]), [paid])
        response = self.doctor_client.get(url, {"q": "fassi"})
        self.assertEqual([i.patient for i in response.context["invoices"]], [other])
        response = self.doctor_client.get(url, {"q": pending.invoice_number})
        self.assertEqual(list(response.context["invoices"]), [pending])
        partial = self.doctor_client.get(url, {"partial": "table", "statut": "pending"}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(partial, "billing/_invoice_table.html")
        self.assertContains(partial, "Reste dû")

    def test_tariffs_page_inline_edit_and_add(self):
        response = self.doctor_client.get(reverse("billing:tariffs"))
        self.assertContains(response, "Échographie")
        response = self.doctor_client.post(
            reverse("billing:tariff_row", args=[self.echo.pk]),
            {"code": "ECHO", "name": "Échographie pelvienne", "price": "250", "is_active": "on", "is_quick_exam": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.echo.refresh_from_db()
        self.assertEqual((self.echo.price, self.echo.is_quick_exam), (Decimal("250"), True))

        response = self.doctor_client.post(reverse("billing:tariff_add"), {"code": "cons", "name": "Doublon", "price": "1"})
        self.assertContains(response, "Ce code existe déjà")
        self.doctor_client.post(reverse("billing:tariff_add"), {"code": "frottis", "name": "Frottis", "price": "150", "is_active": "on"})
        self.assertTrue(MedicalAct.objects.filter(cabinet=self.cabinet, code="FROTTIS", price=Decimal("150")).exists())

    def test_tariffs_link_only_for_doctor(self):
        tariffs = reverse("billing:tariffs")
        self.assertContains(self.doctor_client.get(reverse("billing:index")), tariffs)
        self.assertNotContains(self.assistant_client.get(reverse("billing:index")), tariffs)


class InvoicePdfTest(BillingTestBase):
    def test_invoice_pdf_content(self):
        self.cabinet.ice = "001234567000089"
        self.cabinet.save()
        invoice = self._invoice("350")
        record_payment(invoice, None, "cash", self.assistant)
        invoice.refresh_from_db()
        text = PdfReader(io.BytesIO(generate_invoice_pdf(invoice, save_copy=False))).pages[0].extract_text()
        self.assertIn("FACTURE", text)
        self.assertIn(invoice.invoice_number, text)
        self.assertIn("trois cent cinquante dirhams", text)
        self.assertIn("ACQUITT", text)
        self.assertIn("ICE : 001234567000089", text)
        self.assertNotIn("INPE", text)

    def test_unpaid_invoice_has_no_stamp_and_shows_discount(self):
        invoice = self._invoice("500")
        invoice.discount = Decimal("50")
        invoice.total_amount = Decimal("450")
        invoice.save()
        response = self.assistant_client.get(reverse("billing:invoice_pdf", args=[invoice.pk]))
        text = PdfReader(io.BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Remise", text)
        self.assertIn("quatre cent cinquante dirhams", text)
        self.assertNotIn("ACQUITT", text)


class BackfillMigrationTest(BillingTestBase):
    def test_paid_invoices_get_one_payment_at_paid_at(self):
        paid_at = timezone.now() - timedelta(days=30)
        old = Invoice.objects.create(
            cabinet=self.cabinet, patient=self.patient, total_amount=Decimal("450"),
            status="paid", payment_method="card", paid_at=paid_at,
        )
        pending = self._invoice("200")
        migration = importlib.import_module("apps.billing.migrations.0007_backfill_payments")
        migration.backfill_payments(django_apps, None)
        migration.backfill_payments(django_apps, None)  # idempotent

        payment = Payment.objects.get(invoice=old)
        self.assertEqual((payment.amount, payment.method, payment.paid_at), (Decimal("450"), "card", paid_at))
        self.assertFalse(Payment.objects.filter(invoice=pending).exists())
        old.refresh_from_db()
        self.assertEqual(old.balance_due, Decimal("0"))
