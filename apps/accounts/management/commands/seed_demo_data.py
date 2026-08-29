import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import Profile
from apps.appointments.models import Appointment
from apps.billing.models import MedicalAct
from apps.clinical.models import Consultation, ConsultationAct
from apps.patients.models import Patient

ACTS_CATALOG = [
    ("CONS_GYN", "Consultation gynécologique", 300),
    ("ECHO_OBST", "Échographie obstétricale", 500),
    ("ECHO_PELV", "Échographie pelvienne", 400),
    ("FROTTIS", "Frottis cervico-vaginal", 250),
    ("STERILET", "Pose stérilet", 450),
]

PATIENTS_DATA = [
    ("Fatima", "El Amrani", "AB123456", "0661020304"),
    ("Khadija", "Bennani", "AB234567", "0662030405"),
    ("Salma", "Idrissi", "AB345678", "0663040506"),
    ("Nadia", "Chraibi", "AB456789", "0664050607"),
    ("Meryem", "Tazi", "AB567890", "0665060708"),
    ("Amina", "Fassi", "AB678901", "0666070809"),
    ("Hanane", "Alaoui", "AB789012", "0667080910"),
    ("Ilham", "Berrada", "AB890123", "0668091011"),
    ("Zineb", "Skalli", "AB901234", "0669101112"),
    ("Rajae", "Ouazzani", "AB012345", "0660111213"),
]

APPOINTMENT_STATUSES = [
    Appointment.Status.SCHEDULED,
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
    Appointment.Status.COMPLETED,
]


class Command(BaseCommand):
    help = "Seed demo data: users, medical acts catalog, patients, today's appointments and consultations."

    def handle(self, *args, **options):
        doctor = self._create_user("dr_errmili", "errmili2026", Profile.Role.DOCTOR, "Khadija", "Errmili")
        self._create_user("assistante", "assistante2026", Profile.Role.ASSISTANT, "Assistante", "Cabinet")

        acts = {}
        for code, name, price in ACTS_CATALOG:
            act, _ = MedicalAct.objects.update_or_create(
                code=code, defaults={"name": name, "price": price, "is_active": True}
            )
            acts[code] = act
        self.stdout.write(self.style.SUCCESS(f"{len(acts)} actes médicaux dans le catalogue."))

        today = timezone.localdate()
        base_hour = 9
        created_patients = 0
        created_appointments = 0
        created_consultations = 0

        for i, (first_name, last_name, cin, phone) in enumerate(PATIENTS_DATA):
            patient, was_created = Patient.objects.get_or_create(
                cin=cin,
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "emergency_contact": f"{phone[:4]} (famille)",
                    "allergies": "" if i % 3 else "Pénicilline",
                    "medical_history": "RAS" if i % 2 else "Suivi grossesse antérieure",
                },
            )
            if was_created:
                created_patients += 1

            status = APPOINTMENT_STATUSES[i % len(APPOINTMENT_STATUSES)]
            appt_time = timezone.make_aware(
                timezone.datetime.combine(today, timezone.datetime.min.time())
                + timedelta(hours=base_hour, minutes=30 * i)
            )
            appointment, appt_created = Appointment.objects.get_or_create(
                patient=patient,
                date=appt_time,
                defaults={
                    "status": status,
                    "reason": random.choice(["Consultation de routine", "Suivi grossesse", "Contrôle"]),
                    "whatsapp_status": Appointment.WhatsappStatus.CONFIRMED
                    if status != Appointment.Status.SCHEDULED
                    else Appointment.WhatsappStatus.PENDING,
                },
            )
            if appt_created:
                created_appointments += 1

            if status in (Appointment.Status.IN_CONSULTATION, Appointment.Status.COMPLETED):
                consultation, consult_created = Consultation.objects.get_or_create(
                    appointment=appointment,
                    defaults={
                        "patient": patient,
                        "doctor": doctor,
                        "clinical_notes": "Examen clinique sans particularité.",
                        "diagnostic": "Suivi gynécologique de routine.",
                    },
                )
                if consult_created:
                    created_consultations += 1
                    chosen_codes = random.sample(list(acts.keys()), k=random.choice([1, 2]))
                    for code in chosen_codes:
                        act = acts[code]
                        ConsultationAct.objects.get_or_create(
                            consultation=consultation, act=act, defaults={"price": act.price}
                        )
                    if status == Appointment.Status.COMPLETED:
                        consultation.status = Consultation.Status.VALIDATED
                        consultation.save()

        self.stdout.write(self.style.SUCCESS(f"{created_patients} nouvelles patientes créées."))
        self.stdout.write(self.style.SUCCESS(f"{created_appointments} nouveaux rendez-vous créés."))
        self.stdout.write(self.style.SUCCESS(f"{created_consultations} nouvelles consultations créées."))
        self.stdout.write(self.style.SUCCESS("Seed terminé."))

    @staticmethod
    def _create_user(username, password, role, first_name, last_name):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"first_name": first_name, "last_name": last_name},
        )
        if created:
            user.set_password(password)
            user.save()
        Profile.objects.update_or_create(user=user, defaults={"role": role})
        return user
