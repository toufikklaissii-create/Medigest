from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.clinical.models import Consultation


class SeedDemoDayTest(TestCase):
    def setUp(self):
        cabinet = Cabinet.objects.create(nom="Cabinet Démo", slug="cabinet-demo")
        doctor = User.objects.create_user(username="dr_demo", password="x")
        Profile.objects.update_or_create(user=doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": cabinet})
        for code, price in (("CONS_GYN", "300"), ("ECHO_OBST", "500"), ("FROTTIS", "250")):
            MedicalAct.objects.create(cabinet=cabinet, code=code, name=code, price=Decimal(price))

    def test_billing_states_and_idempotence(self):
        call_command("seed_demo_day", "--today", stdout=StringIO())
        call_command("seed_demo_day", "--today", stdout=StringIO())

        day = timezone.localdate()
        self.assertEqual(Appointment.objects.filter(date__date=day).count(), 9)
        self.assertEqual(Consultation.objects.filter(status=Consultation.Status.VALIDATED).count(), 2)

        pending = Invoice.objects.get(status=Invoice.Status.PENDING)
        self.assertEqual(pending.total_amount, Decimal("800"))
        self.assertEqual(pending.items.count(), 2)

        paid = Invoice.objects.get(status=Invoice.Status.PAID)
        self.assertEqual(paid.total_amount, Decimal("550"))
        self.assertEqual(paid.payment_method, Invoice.PaymentMethod.CASH)
        self.assertEqual(timezone.localtime(paid.paid_at).date(), day)

    def test_default_targets_tomorrow(self):
        call_command("seed_demo_day", stdout=StringIO())
        tomorrow = timezone.localdate() + timedelta(days=1)
        self.assertEqual(Appointment.objects.filter(date__date=tomorrow).count(), 9)
