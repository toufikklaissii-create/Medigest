from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation
from apps.patients.models import Patient

# Patientes fictives — le CIN (préfixe « DM ») sert de clé d'idempotence.
PATIENTS = [
    {
        "cin": "DM100201",
        "first_name": "Salma",
        "last_name": "Bennani",
        "birth_date": (1994, 3, 12),
        "phone": "0661234501",
        "blood_group": "A+",
        "allergies": "",
        "medical_history": "G2P1 — accouchement par voie basse en 2022.\nPas d'antécédent chirurgical.",
        "vitals": {"blood_pressure": "11/7", "weight_kg": "68.50", "height_cm": "164.0"},
        "pregnant": True,
    },
    {
        "cin": "DM100202",
        "first_name": "Khadija",
        "last_name": "El Alaoui",
        "birth_date": (1987, 7, 25),
        "phone": "0662345602",
        "blood_group": "O+",
        "allergies": "Pénicilline",
        "medical_history": "Syndrome des ovaires polykystiques.\nAppendicectomie en 2009.",
        "vitals": {"blood_pressure": "12/8", "weight_kg": "74.00", "height_cm": "160.0"},
    },
    {
        "cin": "DM100203",
        "first_name": "Meryem",
        "last_name": "Tazi",
        "birth_date": (1999, 11, 3),
        "phone": "0663456703",
        "blood_group": "B+",
        "allergies": "",
        "medical_history": "Dysménorrhée primaire.",
        "vitals": {"blood_pressure": "10/6", "weight_kg": "55.20", "height_cm": "167.0"},
    },
    {
        "cin": "DM100204",
        "first_name": "Nadia",
        "last_name": "Chraibi",
        "birth_date": (1979, 1, 18),
        "phone": "0664567804",
        "blood_group": "A-",
        "allergies": "Iode",
        "medical_history": "Hypertension artérielle sous traitement.\nFibrome utérin suivi depuis 2021.",
        "vitals": {"blood_pressure": "14/9", "weight_kg": "81.30", "height_cm": "158.0"},
    },
    {
        "cin": "DM100205",
        "first_name": "Imane",
        "last_name": "Berrada",
        "birth_date": (1991, 5, 30),
        "phone": "0665678905",
        "blood_group": "AB+",
        "allergies": "",
        "medical_history": "Césarienne en 2019.\nAnémie ferriprive traitée.",
        "vitals": {"blood_pressure": "11/7", "weight_kg": "62.00", "height_cm": "170.0"},
    },
    {
        "cin": "DM100206",
        "first_name": "Hajar",
        "last_name": "Ouazzani",
        "birth_date": (2001, 9, 9),
        "phone": "0666789006",
        "blood_group": "O-",
        "allergies": "",
        "medical_history": "Aucun antécédent notable.",
        "vitals": {"blood_pressure": "10/7", "weight_kg": "58.40", "height_cm": "162.0"},
    },
]

# (heure, minute, CIN, motif, statut) — journée de 9 h à 17 h.
APPOINTMENTS = [
    (9, 0, "DM100201", "Suivi grossesse", Appointment.Status.COMPLETED),
    (9, 45, "DM100202", "Consultation de suivi", Appointment.Status.IN_CONSULTATION),
    (10, 30, "DM100203", "Première consultation", Appointment.Status.WAITING),
    (11, 15, "DM100204", "Contrôle", Appointment.Status.ARRIVED),
    (12, 0, "DM100206", "Consultation de routine", Appointment.Status.CANCELLED),
    (14, 0, "DM100205", "Échographie", Appointment.Status.SCHEDULED),
    (15, 15, "DM100201", "Échographie morphologique", Appointment.Status.SCHEDULED),
    (16, 30, "DM100206", "Consultation de routine", Appointment.Status.SCHEDULED),
]

# Statuts pour lesquels l'assistante a déjà saisi les constantes d'accueil.
WITH_VITALS = {
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
    Appointment.Status.COMPLETED,
}

PREGNANCY_DAYS = 20 * 7  # ~20 SA le jour du RDV


class Command(BaseCommand):
    help = (
        "Prépare une journée de démo pour demain : 6 patientes fictives, 8 RDV (9 h–17 h), "
        "constantes et antécédents. Idempotente, ne supprime rien."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        cabinet = Cabinet.objects.first()
        if not cabinet:
            self.stderr.write(self.style.ERROR("Aucun cabinet trouvé — lancez d'abord seed_demo_data."))
            return
        doctor = get_user_model().objects.filter(
            profile__role=Profile.Role.DOCTOR, profile__cabinet=cabinet
        ).first()

        tomorrow = timezone.localdate() + timedelta(days=1)
        lmp = tomorrow - timedelta(days=PREGNANCY_DAYS)

        patients, new_patients = {}, 0
        for spec in PATIENTS:
            patient, created = Patient.objects.get_or_create(
                cabinet=cabinet,
                cin=spec["cin"],
                defaults={
                    "first_name": spec["first_name"],
                    "last_name": spec["last_name"],
                    "birth_date": datetime(*spec["birth_date"]).date(),
                    "phone": spec["phone"],
                    "blood_group": spec["blood_group"],
                    "allergies": spec["allergies"],
                    "medical_history": spec["medical_history"],
                },
            )
            new_patients += created
            patients[spec["cin"]] = (patient, spec)

        new_appointments = new_consultations = 0
        for hour, minute, cin, reason, status in APPOINTMENTS:
            patient, spec = patients[cin]
            appt_dt = timezone.make_aware(datetime.combine(tomorrow, time(hour, minute)))
            appointment, created = Appointment.objects.get_or_create(
                cabinet=cabinet,
                patient=patient,
                date=appt_dt,
                defaults={"status": status, "reason": reason},
            )
            new_appointments += created

            if status not in WITH_VITALS or doctor is None:
                continue
            vitals = spec["vitals"]
            _, created = Consultation.objects.get_or_create(
                appointment=appointment,
                defaults={
                    "cabinet": cabinet,
                    "patient": patient,
                    "doctor": doctor,
                    "blood_pressure": vitals["blood_pressure"],
                    "weight_kg": Decimal(vitals["weight_kg"]),
                    "height_cm": Decimal(vitals["height_cm"]),
                    "last_menstrual_period": lmp if spec.get("pregnant") else None,
                },
            )
            new_consultations += created

        if doctor is None:
            self.stdout.write(self.style.WARNING("Aucun médecin rattaché : constantes non créées."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Journée du {tomorrow:%d/%m/%Y} : {new_patients} patiente(s), "
                f"{new_appointments} RDV, {new_consultations} fiche(s) de constantes créés "
                f"(DDR enceinte : {lmp:%d/%m/%Y})."
            )
        )
