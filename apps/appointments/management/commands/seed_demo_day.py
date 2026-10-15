import argparse
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.clinical.models import Consultation, ConsultationAct
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

# (décalage en minutes depuis --start, CIN, motif, statut) — 9 h → 16 h 30 par défaut.
# (patiente, jour, motif) identifie un RDV : relancer avec un autre --start le déplace.
APPOINTMENTS = [
    (0, "DM100201", "Suivi grossesse", Appointment.Status.COMPLETED),
    (25, "DM100205", "Frottis de dépistage", Appointment.Status.COMPLETED),
    (45, "DM100202", "Consultation de suivi", Appointment.Status.IN_CONSULTATION),
    (90, "DM100203", "Première consultation", Appointment.Status.WAITING),
    (135, "DM100204", "Contrôle", Appointment.Status.ARRIVED),
    (180, "DM100206", "Consultation de routine", Appointment.Status.CANCELLED),
    (300, "DM100205", "Échographie", Appointment.Status.SCHEDULED),
    (375, "DM100201", "Échographie morphologique", Appointment.Status.SCHEDULED),
    (450, "DM100206", "Contrôle", Appointment.Status.SCHEDULED),
]

IN_CONSULTATION_SINCE = timedelta(minutes=15)

# Consultations terminées : validées par le médecin (facture générée par Consultation._bill).
# paid=True → facture déjà encaissée en espèces le jour même (compteur « encaissés aujourd'hui »).
VALIDATED = {
    ("DM100201", "Suivi grossesse"): {"acts": ["CONS_GYN", "ECHO_OBST"], "paid": False},
    ("DM100205", "Frottis de dépistage"): {"acts": ["CONS_GYN", "FROTTIS"], "paid": True},
}

# Statuts pour lesquels l'assistante a déjà saisi les constantes d'accueil.
WITH_VITALS = {
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
    Appointment.Status.COMPLETED,
}

PREGNANCY_DAYS = 20 * 7  # ~20 SA le jour du RDV


def _start_time(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError("format attendu : HH:MM (ex. 09:00)")


class Command(BaseCommand):
    help = (
        "Prépare une journée de démo pour demain : 6 patientes fictives, 9 RDV (9 h–17 h), "
        "constantes, antécédents, une facture à encaisser et une déjà payée. Idempotente, ne supprime rien."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start", type=_start_time, default=time(9, 0),
            help="Heure du premier RDV, HH:MM (défaut : 09:00).",
        )
        parser.add_argument(
            "--today", action="store_true",
            help="Cale la journée sur aujourd'hui (défaut : demain) ; le RDV « en consultation » "
            "est alors placé il y a ~15 min.",
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

        day = timezone.localdate() + timedelta(days=0 if options["today"] else 1)
        start = timezone.make_aware(datetime.combine(day, options["start"]))
        lmp = day - timedelta(days=PREGNANCY_DAYS)
        # Le RDV en cours a commencé il y a ~15 min (arrondi à 5 min) si la journée est aujourd'hui.
        consult_dt = (timezone.localtime() - IN_CONSULTATION_SINCE).replace(second=0, microsecond=0)
        consult_dt -= timedelta(minutes=consult_dt.minute % 5)

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

        new_appointments = new_consultations = validated = paid = 0
        moved = 0
        for offset, cin, reason, status in APPOINTMENTS:
            patient, spec = patients[cin]
            appt_dt = start + timedelta(minutes=offset)
            if status == Appointment.Status.IN_CONSULTATION and consult_dt.date() == day:
                appt_dt = consult_dt
            appointment = Appointment.objects.filter(
                cabinet=cabinet, patient=patient, date__date=day, reason=reason
            ).first()
            if appointment is None:
                appointment = Appointment.objects.create(
                    cabinet=cabinet, patient=patient, date=appt_dt, status=status, reason=reason
                )
                new_appointments += 1
            elif appointment.date != appt_dt or appointment.status != status:
                appointment.date, appointment.status = appt_dt, status
                appointment.save(update_fields=["date", "status"])
                moved += 1

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

            billing = VALIDATED.get((cin, reason))
            if billing:
                v, p = self._validate(appointment, cabinet, billing)
                validated += v
                paid += p

        if doctor is None:
            self.stdout.write(self.style.WARNING("Aucun médecin rattaché : constantes non créées."))
        self.stdout.write(
            self.style.SUCCESS(
                f"Journée du {day:%d/%m/%Y} dès {options['start']:%H:%M} : {new_patients} patiente(s), "
                f"{new_appointments} RDV créés, {moved} recalé(s), {new_consultations} fiche(s) de constantes, "
                f"{validated} consultation(s) validée(s), {paid} facture(s) encaissée(s) "
                f"(DDR enceinte : {lmp:%d/%m/%Y})."
            )
        )

    def _validate(self, appointment, cabinet, billing):
        """Valide la consultation avec ses actes (→ facture en attente), puis l'encaisse si demandé."""
        consultation = Consultation.objects.filter(appointment=appointment).first()
        if consultation is None:
            return 0, 0
        validated = 0
        if consultation.status != Consultation.Status.VALIDATED:
            acts = MedicalAct.objects.filter(cabinet=cabinet, code__in=billing["acts"])
            missing = set(billing["acts"]) - set(acts.values_list("code", flat=True))
            if missing:
                self.stdout.write(self.style.WARNING(f"Actes absents du catalogue : {', '.join(sorted(missing))}."))
            for act in acts:
                ConsultationAct.objects.get_or_create(
                    consultation=consultation, act=act, defaults={"price": act.price}
                )
            consultation.diagnostic = consultation.diagnostic or "Examen sans particularité."
            consultation.status = Consultation.Status.VALIDATED
            consultation.save()  # transition → Consultation._bill() crée la facture en attente
            validated = 1
            consultation.refresh_from_db()

        invoice = consultation.invoice
        if billing["paid"] and invoice and invoice.status == Invoice.Status.PENDING:
            invoice.status = Invoice.Status.PAID
            invoice.payment_method = Invoice.PaymentMethod.CASH
            # Encaissée à la sortie de la patiente, le jour du RDV.
            invoice.paid_at = appointment.date + timedelta(minutes=appointment.duration_minutes + 5)
            invoice.save(update_fields=["status", "payment_method", "paid_at"])
            return validated, 1
        return validated, 0
