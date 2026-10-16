import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import CashClosing, Invoice, MedicalAct, Payment
from apps.clinical.models import Consultation, PatientDocument
from apps.patients.models import Patient

ACTS = {"CONS_GYN": "300", "ECHO_OBST": "500", "ECHO_PELV": "400", "FROTTIS": "250",
        "STERILET": "450", "PRELEV_BACT": "150"}


class SeedDemoMeetingTest(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls.media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Dr ERRMILI", slug="cabinet-dr-errmili")
        for username, role in (("dr", Profile.Role.DOCTOR), ("assist", Profile.Role.ASSISTANT)):
            user = User.objects.create_user(username=username, password="x")
            Profile.objects.update_or_create(user=user, defaults={"role": role, "cabinet": self.cabinet})
        for code, price in ACTS.items():
            MedicalAct.objects.create(cabinet=self.cabinet, code=code, name=code, price=Decimal(price))
        # Donnée réelle hors démo : ne doit jamais être touchée.
        self.real = Patient.objects.create(cabinet=self.cabinet, first_name="Réelle", last_name="Patiente")

    def _counts(self):
        return {
            model.__name__: model.objects.count()
            for model in (Patient, Appointment, Consultation, Invoice, Payment, CashClosing, PatientDocument)
        }

    def test_runs_twice_without_duplicates_and_today_after_start(self):
        day = date(2026, 10, 16)
        args = ["seed_demo_meeting", "--day", day.isoformat(), "--start", "20:00"]
        call_command(*args, stdout=StringIO())
        first = self._counts()
        call_command(*args, stdout=StringIO())
        self.assertEqual(self._counts(), first)
        self.assertTrue(Patient.objects.filter(pk=self.real.pk).exists())

        today = Appointment.objects.filter(date__date=day)
        start = timezone.make_aware(datetime.combine(day, time(20, 0)))
        self.assertEqual(today.count(), 8)
        self.assertTrue(all(appt.date >= start for appt in today))
        statuses = sorted(today.values_list("status", flat=True))
        self.assertEqual(statuses, sorted(
            ["arrived", "waiting", "in_consultation"] + ["scheduled"] * 5))
        # Rien de terminé ni d'encaissé le jour même.
        self.assertFalse(Payment.objects.filter(paid_at__gte=start - timedelta(hours=20)).exists())

        self.assertEqual(Invoice.objects.filter(status=Invoice.Status.CANCELLED).count(), 1)
        self.assertEqual(Invoice.objects.filter(status=Invoice.Status.PENDING).count(), 1)
        partial = Invoice.objects.get(status=Invoice.Status.PARTIAL)
        self.assertEqual(partial.balance_due, Decimal("300"))
        self.assertTrue(Invoice.objects.filter(is_free=True, total_amount=0).exists())
        self.assertEqual(set(Payment.objects.values_list("method", flat=True)),
                         {"cash", "card", "check", "transfer"})
        self.assertEqual(CashClosing.objects.exclude(difference=0).count(), 1)
        self.assertEqual(PatientDocument.objects.count(), 3)

    def test_start_option_moves_evening(self):
        day = date(2026, 10, 16)
        call_command("seed_demo_meeting", "--day", day.isoformat(), "--start", "18:30", stdout=StringIO())
        first = timezone.localtime(Appointment.objects.filter(date__date=day).earliest("date").date)
        self.assertEqual(first.time(), time(18, 30))
