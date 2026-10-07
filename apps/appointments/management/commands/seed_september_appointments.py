import calendar
import random
from datetime import date, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Cabinet
from apps.appointments.models import Appointment
from apps.patients.models import Patient

DAY_START_MINUTES = 8 * 60 + 30
DAY_END_MINUTES = 18 * 60 + 30
SLOT_MINUTES = 30

REASONS = [
    "Consultation de suivi",
    "Échographie",
    "Contrôle",
    "Première consultation",
    "Suivi grossesse",
    "Consultation de routine",
]

STATUS_POOL = [
    Appointment.Status.SCHEDULED,
    Appointment.Status.SCHEDULED,
    Appointment.Status.COMPLETED,
    Appointment.Status.COMPLETED,
    Appointment.Status.CANCELLED,
]


def _day_slots():
    slots = []
    minutes = DAY_START_MINUTES
    while minutes <= DAY_END_MINUTES - SLOT_MINUTES:
        slots.append(time(minutes // 60, minutes % 60))
        minutes += SLOT_MINUTES
    return slots


class Command(BaseCommand):
    help = "Crée des rendez-vous fictifs sur tout le mois de septembre (3 à 5 par jour) pour les tests."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=None, help="Année cible (défaut: année courante).")
        parser.add_argument(
            "--skip-sundays",
            action="store_true",
            default=True,
            help="N'ajoute pas de rendez-vous le dimanche (activé par défaut).",
        )

    def handle(self, *args, **options):
        cabinet = Cabinet.objects.first()
        if not cabinet:
            self.stderr.write(self.style.ERROR("Aucun cabinet trouvé — lancez d'abord seed_demo_data."))
            return

        patients = list(Patient.objects.filter(cabinet=cabinet))
        if not patients:
            self.stderr.write(self.style.ERROR("Aucune patiente trouvée — lancez d'abord seed_demo_data."))
            return

        year = options["year"] or timezone.localdate().year
        month = 9
        days_in_month = calendar.monthrange(year, month)[1]
        slots = _day_slots()

        created_count = 0
        for day in range(1, days_in_month + 1):
            current_date = date(year, month, day)
            if options["skip_sundays"] and current_date.weekday() == 6:
                continue

            nb_appointments = random.randint(3, 5)
            day_slots = random.sample(slots, k=min(nb_appointments, len(slots)))
            day_patients = random.sample(patients, k=min(nb_appointments, len(patients)))

            for slot_time, patient in zip(sorted(day_slots), day_patients):
                appt_dt = timezone.make_aware(
                    timezone.datetime.combine(current_date, slot_time)
                )
                status = random.choice(STATUS_POOL)
                _, was_created = Appointment.objects.get_or_create(
                    cabinet=cabinet,
                    patient=patient,
                    date=appt_dt,
                    defaults={
                        "status": status,
                        "reason": random.choice(REASONS),
                        "whatsapp_status": Appointment.WhatsappStatus.PENDING,
                    },
                )
                if was_created:
                    created_count += 1

        self.stdout.write(self.style.SUCCESS(f"{created_count} rendez-vous fictifs créés pour septembre {year}."))
