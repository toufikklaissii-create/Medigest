"""Non-régression : DDR, terme (SA + j) et DPA identiques partout pour une même consultation."""

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import MedicalAct
from apps.clinical import services
from apps.clinical.models import Consultation, pregnancy_dates
from apps.patients.models import Patient


@override_settings(ALLOWED_HOSTS=["testserver"])
class LmpConsistencyTest(TestCase):
    def setUp(self):
        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-test")
        self.doctor = User.objects.create_user(username="dr_lmp", password="testpass123")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="assist_lmp", password="testpass123")
        Profile.objects.update_or_create(user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Salma", last_name="Bennani")

    @override_settings(TIME_ZONE="Europe/Paris")  # UTC+2 : 00h30 local tombe la veille en UTC
    def test_same_lmp_term_and_due_date_on_every_screen_and_pdf(self):
        # RDV à 00h30 heure locale = la veille en UTC : piège classique de fuseau.
        visit_day = timezone.localdate() - timedelta(days=1)
        appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, status=Appointment.Status.ARRIVED,
            date=timezone.make_aware(datetime.combine(visit_day, time(0, 30))),
        )
        self.assertNotEqual(appt.date.astimezone(dt_timezone.utc).date(), visit_day)  # bien « la veille » en UTC
        lmp = visit_day - timedelta(days=140)
        consultation = Consultation.objects.create(
            appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            last_menstrual_period=lmp,
        )
        expected = pregnancy_dates(lmp, visit_day)
        self.assertEqual((expected["weeks"], expected["days"]), (20, 0))
        term = "20 SA + 0 j"
        due = expected["due_date"].strftime("%d/%m/%Y")

        doctor = Client()
        doctor.login(username="dr_lmp", password="testpass123")
        cockpit = doctor.get(reverse("clinical:consultation_detail", args=[appt.pk])).content.decode()
        self.assertIn(term, cockpit)
        self.assertIn(due, cockpit)
        self.assertIn(timezone.localtime(appt.date).strftime("%H:%M"), cockpit)

        dossier = doctor.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn(lmp.strftime("%d/%m/%Y"), dossier)
        self.assertIn(term, dossier)

        assistant = Client()
        assistant.login(username="assist_lmp", password="testpass123")
        panel = assistant.get(reverse("appointments:reception_panel", args=[appt.pk])).content.decode()
        self.assertIn(f'data-ddr="{lmp.isoformat()}"', panel)
        self.assertIn(f'data-reference="{visit_day.isoformat()}"', panel)  # jour local, pas UTC

        with mock.patch.object(services, "render_pdf", return_value=b"%PDF") as render:
            services.generate_report_pdf(consultation, save_copy=False)
        context = render.call_args[0][1]
        self.assertEqual(context["last_menstrual_period"], lmp)
        self.assertEqual(context["gestational_age"], term)
        self.assertEqual(context["due_date"], expected["due_date"])

    def test_report_pdf_ignores_stale_stored_gestational_age(self):
        appt = Appointment.objects.create(cabinet=self.cabinet, patient=self.patient, date=timezone.now())
        lmp = timezone.localdate() - timedelta(days=12 * 7 + 3)
        consultation = Consultation.objects.create(
            appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor,
            last_menstrual_period=lmp, gestational_age_weeks=30,  # valeur périmée
        )
        with mock.patch.object(services, "render_pdf", return_value=b"%PDF") as render:
            services.generate_report_pdf(consultation, save_copy=False)
        self.assertEqual(render.call_args[0][1]["gestational_age"], "12 SA + 3 j")

    def test_seed_keeps_one_lmp_per_pregnancy_across_days(self):
        for code in ("CONS_GYN", "ECHO_OBST", "FROTTIS"):
            MedicalAct.objects.create(cabinet=self.cabinet, code=code, name=code, price=Decimal("100"))
        call_command("seed_demo_day", "--today", stdout=StringIO())
        call_command("seed_demo_day", stdout=StringIO())  # demain
        lmps = set(
            Consultation.objects.filter(patient__cin="DM100201", last_menstrual_period__isnull=False)
            .values_list("last_menstrual_period", flat=True)
        )
        self.assertEqual(len(lmps), 1, lmps)
        self.assertEqual(lmps.pop(), timezone.localdate() - timedelta(days=140))
