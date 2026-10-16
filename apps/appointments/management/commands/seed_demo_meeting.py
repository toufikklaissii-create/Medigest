"""Jeu de démo pour la réunion : soirée de RDV + 30 jours d'historique clinique et comptable.

Rejouable : à chaque passage, les données rattachées aux patientes de démo (CIN « DMR… »)
et les clôtures de caisse posées par cette commande sont supprimées puis recréées.
Rien d'autre n'est touché.
"""
import argparse
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import CashClosing, Invoice, MedicalAct, Payment
from apps.billing.reports import expected_cash
from apps.billing.services import cancel_invoice, record_payment
from apps.clinical.models import Consultation, ConsultationAct, Document, PatientDocument
from apps.patients.models import Patient

CIN_PREFIX = "DMR"
SLOT_MINUTES = 25
CLOSING_HOUR = time(19, 0)
CLOSING_OK = "Fond de caisse recompté, conforme."
CLOSING_GAP = "Écart de 20,00 DH : erreur de rendu de monnaie."
CLOSING_GAP_AMOUNT = Decimal("20")
REQUIRED_ACTS = {"CONS_GYN", "ECHO_OBST", "ECHO_PELV", "FROTTIS", "STERILET", "PRELEV_BACT"}

Status = Appointment.Status
Method = Invoice.PaymentMethod

# key, CIN, prénom, nom, naissance, téléphone, groupe, allergies, antécédents
PATIENTS = [
    ("t1", "DMR20101", "Hind", "Benjelloun", (1996, 4, 14), "0661482735", "A+", "",
     "Primigeste. Aucun antécédent notable."),
    ("t2", "DMR20102", "Souad", "El Fassi", (1992, 9, 2), "0662519046", "O+", "",
     "G2P1 — accouchement par voie basse en 2021."),
    ("t3", "DMR20103", "Latifa", "Amrani", (1989, 1, 23), "0663720518", "B+", "Pénicilline",
     "G3P2 — 2 accouchements par voie basse.\nHTA gravidique lors de la 2e grossesse (2020)."),
    ("gyn", "DMR20104", "Naima", "Kettani", (1984, 6, 7), "0664093187", "A-", "",
     "G2P2. Contraception orale arrêtée en 2026."),
    ("inf", "DMR20105", "Rim", "Sbai", (1993, 11, 30), "0665831402", "AB+", "",
     "Désir de grossesse depuis 2 ans, cycles irréguliers (35–45 j).\nConjoint 36 ans, sans antécédent."),
    ("new", "DMR20106", "Ghizlane", "Rami", (1998, 2, 19), "0766214859", "", "",
     ""),
    ("relance", "DMR20107", "Asmae", "Lahlou", (1990, 8, 11), "0667458213", "O+", "",
     "Kyste ovarien fonctionnel en 2025, régressif."),
    ("confirme", "DMR20108", "Siham", "Mansouri", (1986, 3, 5), "0768390124", "B-", "Iode",
     "Fibrome utérin interstitiel de 2 cm, surveillance."),
    ("invalide", "DMR20109", "Houda", "Tahiri", (2000, 12, 17), "06123", "", "",
     "Dysménorrhée primaire."),
    ("annulee", "DMR20110", "Kawtar", "Bouzidi", (1995, 5, 28), "0669127654", "A+", "",
     "Aucun antécédent notable."),
    ("attente", "DMR20111", "Sanae", "Chaoui", (1981, 10, 9), "0770546318", "O-", "",
     "Hypothyroïdie substituée (Lévothyrox 75 µg)."),
]

# Grossesses : DDR = jour de démo − terme visé (en jours).
LMP_AGE_DAYS = {"t1": 8 * 7, "t2": 22 * 7, "t3": 34 * 7}

# Visites passées : (patiente, jours avant --day, heure, motif, actes, constantes, clinique,
#                    facturation). Facturation : None (impayée), "free", "cancel",
#                    ou liste de (mode, montant | None = solde, référence).
HISTORY = [
    # 1. Grossesse T1 — 1re consultation à 6 SA + 4 j.
    ("t1", 10, time(10, 0), "Première consultation de grossesse", ["CONS_GYN", "ECHO_OBST"],
     ("11/7", "58.40", "165.0"),
     {"clinical_exam": "Bon état général. Seins souples. Col fermé, pas de saignement.",
      "ultrasound_notes": "Échographie de datation : grossesse intra-utérine évolutive, embryon unique, "
                          "LCC 7 mm compatible avec 6 SA + 4 j. Activité cardiaque présente.",
      "diagnostic": "Grossesse intra-utérine évolutive de 6 SA + 4 j.",
      "clinical_notes": "Bilan prénatal du 1er trimestre prescrit. Contrôle à 8 SA.",
      "prescription": "Acide folique 0,4 mg — 1 comprimé par jour jusqu'à 12 SA\n"
                      "NFS, groupe sanguin et rhésus, RAI\n"
                      "Sérologies : toxoplasmose, rubéole, syphilis, VIH, hépatite B\n"
                      "Glycémie à jeun, ECBU"},
     [(Method.CASH, None, "")]),
    # 2. Grossesse T2 — 3 visites, poids/TA qui évoluent, écho morphologique à 21 SA.
    ("t2", 84, time(11, 0), "Suivi grossesse", ["CONS_GYN", "ECHO_OBST"],
     ("10/6", "61.00", "162.0"),
     {"ultrasound_notes": "Clarté nucale 1,4 mm. Biométries conformes à 10 SA.",
      "diagnostic": "Grossesse évolutive de 10 SA, échographie du 1er trimestre normale."},
     [(Method.CASH, None, "")]),
    ("t2", 42, time(15, 30), "Suivi grossesse", ["CONS_GYN"],
     ("11/7", "63.50", "162.0"),
     {"clinical_exam": "Hauteur utérine conforme. BCF perçus au doppler.",
      "diagnostic": "Grossesse de 16 SA d'évolution normale. Bilan sanguin rassurant."},
     [(Method.CARD, None, "")]),
    ("t2", 7, time(9, 30), "Échographie morphologique", ["CONS_GYN", "ECHO_OBST"],
     ("11/7", "66.00", "162.0"),
     {"ultrasound_notes": "Échographie morphologique à 21 SA : morphologie fœtale sans anomalie décelable. "
                          "Biométries au 50e percentile. Placenta antérieur normalement inséré. "
                          "Liquide amniotique normal.",
      "diagnostic": "Grossesse de 21 SA, échographie morphologique normale."},
     [(Method.CASH, None, "")]),
    # 3. Grossesse T3 — TA qui monte, lettre au confrère, chèque partiel.
    ("t3", 34, time(10, 30), "Suivi grossesse", ["CONS_GYN"],
     ("12/8", "72.00", "160.0"),
     {"diagnostic": "Grossesse de 29 SA d'évolution normale."},
     [(Method.CARD, None, "")]),
    ("t3", 6, time(16, 0), "Suivi grossesse 3e trimestre", ["CONS_GYN", "ECHO_OBST"],
     ("14/9", "74.50", "160.0"),
     {"clinical_exam": "TA 14/9 à deux reprises. Œdèmes discrets des membres inférieurs. "
                       "Bandelette urinaire : protéinurie négative.",
      "ultrasound_notes": "Présentation céphalique. Biométries au 40e percentile. Doppler ombilical normal.",
      "diagnostic": "Grossesse de 33 SA. HTA gravidique à surveiller (antécédent en 2020).",
      "clinical_notes": "Bilan pré-éclampsie demandé. Avis cardiologique. Autosurveillance tensionnelle.",
      "letter": "Cher confrère,\n\n"
                "Je vous adresse Madame Latifa Amrani, 37 ans, G3P2, enceinte de 33 SA, pour avis "
                "cardiologique.\n\n"
                "Elle présente ce jour une tension artérielle à 14/9 confirmée à deux reprises, avec des "
                "œdèmes discrets des membres inférieurs et une protéinurie négative à la bandelette. "
                "Antécédent d'HTA gravidique lors de sa précédente grossesse en 2020.\n\n"
                "Un bilan pré-éclampsie est en cours. Je vous serais reconnaissante de bien vouloir "
                "évaluer l'indication d'un traitement antihypertenseur compatible avec la grossesse.\n\n"
                "Confraternellement,\nDr ERRMILI Khadija"},
     [(Method.CHECK, Decimal("500"), "CHQ 4471203")]),
    # 4. Suivi gynécologique — frottis payé, puis contrôle gratuit (facture à 0 DH).
    ("gyn", 21, time(11, 30), "Frottis de dépistage", ["CONS_GYN", "FROTTIS"],
     ("12/7", "69.00", "163.0"),
     {"clinical_exam": "Col sain à l'examen au spéculum. Seins sans anomalie palpable.",
      "diagnostic": "Examen gynécologique normal. Frottis cervico-vaginal réalisé.",
      "clinical_notes": "Souhaite un DIU au cuivre : pose à programmer après le résultat du frottis."},
     [(Method.CARD, None, "")]),
    ("gyn", 9, time(17, 0), "Résultat de frottis", ["CONS_GYN"],
     ("12/7", "68.60", "163.0"),
     {"diagnostic": "Frottis normal (NILM). Pas de contre-indication à la pose de DIU.",
      "clinical_notes": "Contrôle gratuit : remise du résultat. Pose de stérilet programmée."},
     "free"),
    # 5. Infertilité du couple — bilan puis compte rendu détaillé.
    ("inf", 40, time(10, 0), "Consultation infertilité", ["CONS_GYN", "ECHO_PELV"],
     ("11/7", "57.00", "168.0"),
     {"clinical_exam": "IMC 20,2. Pilosité normale. Examen gynécologique sans particularité.",
      "ultrasound_notes": "Utérus antéversé de taille normale, endomètre fin. Ovaires d'aspect "
                          "multifolliculaire (CFA 26 au total).",
      "diagnostic": "Infertilité primaire de 2 ans. Suspicion de dysovulation.",
      "prescription": "Bilan hormonal à J3 du cycle : FSH, LH, œstradiol, AMH, prolactine, TSH\n"
                      "Testostérone totale, 17-OH progestérone\n"
                      "Hystérosalpingographie en 1re partie de cycle\n"
                      "Spermogramme et spermocytogramme du conjoint"},
     [(Method.TRANSFER, None, "VIR 20260906-118")]),
    ("inf", 12, time(14, 30), "Résultats du bilan d'infertilité", ["CONS_GYN"],
     ("11/7", "57.20", "168.0"),
     {"clinical_exam": "Examen clinique inchangé.",
      "ultrasound_notes": "Hystérosalpingographie : cavité utérine normale, trompes perméables "
                          "des deux côtés avec bon brassage du produit de contraste.",
      "diagnostic": "Syndrome des ovaires polykystiques (critères de Rotterdam : oligo-anovulation "
                    "et ovaires multifolliculaires). Trompes perméables.",
      "clinical_notes": "Bilan hormonal : AMH 6,8 ng/mL (élevée), LH/FSH 2,1, testostérone 0,62 ng/mL, "
                        "prolactine et TSH normales.\n"
                        "Spermogramme du conjoint en attente.\n"
                        "Conduite à tenir : règles hygiéno-diététiques, induction de l'ovulation par "
                        "citrate de clomifène 50 mg de J3 à J7 avec monitorage échographique à J12. "
                        "Réévaluation après 3 cycles ; orientation vers un centre d'AMP en cas d'échec."},
     [(Method.CASH, None, "")]),
    # 7. Patientes rappelées pour J+1 / J+2 : historique de caisse.
    ("relance", 27, time(9, 0), "Consultation de suivi", ["CONS_GYN"],
     ("11/7", "64.00", "166.0"),
     {"ultrasound_notes": "Kyste ovarien droit non retrouvé.",
      "diagnostic": "Régression complète du kyste fonctionnel."},
     [(Method.CASH, None, "")]),
    ("confirme", 15, time(12, 0), "Contrôle fibrome", ["CONS_GYN", "ECHO_PELV"],
     ("13/8", "78.00", "158.0"),
     {"ultrasound_notes": "Fibrome interstitiel fundique de 22 mm, stable.",
      "diagnostic": "Fibrome utérin stable, surveillance annuelle."},
     [(Method.CARD, None, "")]),
    ("invalide", 3, time(10, 0), "Douleurs pelviennes", ["CONS_GYN"],
     ("10/6", "54.00", "161.0"),
     {"diagnostic": "Dysménorrhée primaire. Antalgiques en début de règles."},
     [(Method.CASH, None, "")]),
    # 8. Facture annulée (avec motif) et facture restée à encaisser.
    ("annulee", 24, time(16, 30), "Consultation gynécologique", ["CONS_GYN"],
     ("11/7", "60.00", "164.0"),
     {"diagnostic": "Examen gynécologique normal."},
     [(Method.CHECK, None, "CHQ 0098431")]),
    ("annulee", 5, time(11, 0), "Échographie pelvienne", ["CONS_GYN", "ECHO_PELV"],
     ("11/7", "60.20", "164.0"),
     {"diagnostic": "Échographie pelvienne normale."},
     "cancel"),
    ("attente", 29, time(15, 0), "Bilan gynécologique annuel", ["CONS_GYN", "FROTTIS"],
     ("12/8", "71.00", "157.0"),
     {"diagnostic": "Examen normal. Frottis réalisé."},
     [(Method.TRANSFER, None, "VIR 20260917-044")]),
    ("attente", 2, time(9, 30), "Leucorrhées", ["CONS_GYN", "PRELEV_BACT"],
     ("12/8", "71.40", "157.0"),
     {"diagnostic": "Vaginose probable, prélèvement bactériologique en cours.",
      "prescription": "Ovules antifongiques — 1 ovule au coucher pendant 3 jours\n"
                      "Toilette intime avec savon à pH neutre"},
     None),
]

CANCEL_REASON = "Doublon : l'échographie avait déjà été facturée sur la consultation précédente."

# Soirée de démo : (patiente, motif, statut, constantes de l'accueil ou None).
EVENING = [
    ("t3", "Suivi grossesse — contrôle tensionnel", Status.IN_CONSULTATION, ("14/9", "75.20", "160.0")),
    ("t2", "Suivi grossesse 22 SA", Status.WAITING, ("11/7", "66.80", "162.0")),
    ("new", "Première consultation", Status.ARRIVED, ("12/7", "63.50", "167.0")),
    ("t1", "Contrôle grossesse 8 SA", Status.SCHEDULED, None),
    ("inf", "Suivi infertilité — spermogramme", Status.SCHEDULED, None),
    ("gyn", "Pose de stérilet", Status.SCHEDULED, None),
    ("annulee", "Consultation de contrôle", Status.SCHEDULED, None),
    ("attente", "Résultat du prélèvement", Status.SCHEDULED, None),
]

# RDV J+1 / J+2 : (patiente, jours après --day, heure, motif, statut WhatsApp, rappel il y a N h).
UPCOMING = [
    ("relance", 1, time(10, 0), "Contrôle échographique", Appointment.WhatsappStatus.SENT, 30),
    ("confirme", 1, time(11, 0), "Suivi fibrome", Appointment.WhatsappStatus.CONFIRMED, 26),
    ("invalide", 2, time(9, 30), "Consultation de suivi", Appointment.WhatsappStatus.PENDING, None),
]


def _hhmm(value):
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError("format attendu : HH:MM (ex. 20:00)")


def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("format attendu : AAAA-MM-JJ (ex. 2026-10-16)")


def _past_day(day, days_ago):
    """Jour ouvré `days_ago` jours avant `day` (un dimanche recule au samedi)."""
    past = day - timedelta(days=days_ago)
    return past - timedelta(days=1) if past.weekday() == 6 else past


def _aware(day, at):
    return timezone.make_aware(datetime.combine(day, at))


def _lab_report_pdf(title, lines):
    """Compte rendu de laboratoire fictif, rendu en image puis enregistré en PDF."""
    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle((80, 80, 1160, 200), outline=(90, 120, 100), width=3)
    draw.text((110, 110), "LABORATOIRE D'ANALYSES MEDICALES (document de demonstration)", fill=(40, 60, 50))
    draw.text((110, 150), title, fill=(0, 0, 0))
    y = 260
    for line in lines:
        draw.text((110, y), line, fill=(30, 30, 30))
        y += 44
    buffer = io.BytesIO()
    page.save(buffer, "PDF", resolution=150)
    return buffer.getvalue()


def _ultrasound_jpeg():
    """Cliché d'échographie fictif : secteur gris bruité sur fond noir."""
    width, height = 800, 600
    noise = Image.effect_noise((width, height), 60).filter(ImageFilter.GaussianBlur(1.5))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).pieslice((-200, -480, 1000, 720), 55, 125, fill=255)
    image = Image.new("L", (width, height), 0)
    image.paste(noise, mask=mask)
    draw = ImageDraw.Draw(image)
    draw.ellipse((300, 260, 520, 420), fill=20)  # poche amniotique
    draw.ellipse((350, 300, 450, 380), fill=150)  # profil fœtal
    draw.text((20, 20), "ECHO MORPHO 21 SA - DEMO", fill=230)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=85)
    return buffer.getvalue()


class Command(BaseCommand):
    help = (
        "Données de démo pour la réunion : 8 RDV le soir (dès --start, toutes les 25 min), "
        "30 jours d'historique (grossesses, gynéco, infertilité), factures, paiements et clôtures. "
        "Rejouable : ne remplace que les données de démo qu'elle a créées."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start", type=_hhmm, default=time(20, 0),
                            help="Heure du premier RDV du jour, HH:MM (défaut : 20:00).")
        parser.add_argument("--day", type=_day, default=None,
                            help="Jour de la réunion, AAAA-MM-JJ (défaut : aujourd'hui).")
        parser.add_argument("--cabinet", default="cabinet-dr-errmili",
                            help="Slug du cabinet (défaut : cabinet-dr-errmili).")

    @transaction.atomic
    def handle(self, *args, **options):
        cabinet = Cabinet.objects.filter(slug=options["cabinet"]).first()
        if cabinet is None:
            raise CommandError(f"Cabinet « {options['cabinet']} » introuvable.")
        users = get_user_model().objects.filter(profile__cabinet=cabinet)
        self.doctor = users.filter(profile__role=Profile.Role.DOCTOR).order_by("pk").first()
        self.assistant = users.filter(profile__role=Profile.Role.ASSISTANT).order_by("pk").first()
        if self.doctor is None:
            raise CommandError("Aucune doctoresse rattachée à ce cabinet.")
        self.acts = {a.code: a for a in MedicalAct.objects.filter(cabinet=cabinet, code__in=REQUIRED_ACTS)}
        missing = REQUIRED_ACTS - set(self.acts)
        if missing:
            raise CommandError(f"Actes absents du catalogue : {', '.join(sorted(missing))}.")

        self.cabinet = cabinet
        self.day = options["day"] or timezone.localdate()
        self.lmps = {key: self.day - timedelta(days=age) for key, age in LMP_AGE_DAYS.items()}

        self._purge()
        patients = self._patients()
        payment_days = set()
        for spec in HISTORY:
            payment_days |= self._past_visit(patients[spec[0]], spec)
        self._documents(patients)
        self._evening(patients, options["start"])
        self._upcoming(patients)
        closings = self._closings(payment_days)

        self.stdout.write(self.style.SUCCESS(
            f"Démo du {self.day:%d/%m/%Y} dès {options['start']:%H:%M} : {len(patients)} patientes, "
            f"{len(EVENING)} RDV ce soir, {len(UPCOMING)} RDV à J+1/J+2, {len(HISTORY)} visites passées, "
            f"{closings} clôture(s) de caisse."
        ))
        for key, patient in patients.items():
            self.stdout.write(f"  {patient.patient_number}  {patient.full_name}  ({patient.phone})")

    # ── Nettoyage ────────────────────────────────────────────────────────────

    def _purge(self):
        demo = Patient.objects.filter(cabinet=self.cabinet, cin__startswith=CIN_PREFIX)
        payments = Payment.objects.filter(invoice__patient__in=demo)
        days = {timezone.localtime(p).date() for p in payments.values_list("paid_at", flat=True)}
        CashClosing.objects.filter(
            cabinet=self.cabinet, date__in=days, note__in=[CLOSING_OK, CLOSING_GAP]
        ).delete()
        payments.delete()
        for document in PatientDocument.objects.filter(patient__in=demo):
            document.file.delete(save=False)
        # Patientes conservées (N° de dossier stable) ; RDV, consultations, factures, documents en cascade.
        Appointment.objects.filter(patient__in=demo).delete()
        Invoice.objects.filter(patient__in=demo).delete()
        PatientDocument.objects.filter(patient__in=demo).delete()

    # ── Patientes ────────────────────────────────────────────────────────────

    def _patients(self):
        patients = {}
        for key, cin, first, last, birth, phone, blood, allergies, history in PATIENTS:
            patient, _ = Patient.objects.update_or_create(
                cabinet=self.cabinet, cin=cin,
                defaults={
                    "first_name": first, "last_name": last, "birth_date": date(*birth),
                    "phone": phone, "blood_group": blood, "allergies": allergies,
                    "medical_history": history,
                    "organisme_social": "CNSS" if key in {"t2", "t3", "gyn"} else "",
                },
            )
            patients[key] = patient
        return patients

    # ── Historique ───────────────────────────────────────────────────────────

    def _consultation(self, patient, key, appointment, vitals, **fields):
        bp, weight, height = vitals
        return Consultation.objects.create(
            cabinet=self.cabinet, appointment=appointment, patient=patient, doctor=self.doctor,
            blood_pressure=bp, weight_kg=Decimal(weight), height_cm=Decimal(height),
            last_menstrual_period=self.lmps.get(key), **fields,
        )

    def _past_visit(self, patient, spec):
        key, days_ago, at, reason, acts, vitals, clinical, billing = spec
        visit_day = _past_day(self.day, days_ago)
        when = _aware(visit_day, at)
        appointment = Appointment.objects.create(
            cabinet=self.cabinet, patient=patient, date=when, duration_minutes=SLOT_MINUTES,
            status=Status.COMPLETED, reason=reason,
            whatsapp_status=Appointment.WhatsappStatus.CONFIRMED,
        )
        clinical = dict(clinical)
        prescription = clinical.pop("prescription", "")
        letter = clinical.pop("letter", "")
        lmp = self.lmps.get(key)
        if lmp:
            clinical["gestational_age_weeks"] = (visit_day - lmp).days // 7
        consultation = self._consultation(
            patient, key, appointment, vitals, billing_free=billing == "free", **clinical
        )
        for code in acts:
            ConsultationAct.objects.create(consultation=consultation, act=self.acts[code],
                                           price=self.acts[code].price)
        consultation.status = Consultation.Status.VALIDATED
        consultation.save()  # → Consultation._bill() : facture aux tarifs du catalogue
        consultation.refresh_from_db()
        for doc_type, content in ((Document.DocumentType.PRESCRIPTION, prescription),
                                  (Document.DocumentType.LETTER, letter)):
            if content:
                doc = Document.objects.create(consultation=consultation, document_type=doc_type, content=content)
                Document.objects.filter(pk=doc.pk).update(created_at=when)
        Consultation.objects.filter(pk=consultation.pk).update(created_at=when)

        invoice = consultation.invoice
        Invoice.objects.filter(pk=invoice.pk).update(created_at=when + timedelta(minutes=20))
        days = set()
        if billing == "cancel":
            cancel_invoice(invoice, CANCEL_REASON, self.doctor)
            Invoice.objects.filter(pk=invoice.pk).update(cancelled_at=when + timedelta(hours=2))
        elif isinstance(billing, list):
            paid_at = when + timedelta(minutes=30)
            for method, amount, reference in billing:
                payment = record_payment(invoice, amount, method, self.assistant, reference, paid_at=paid_at)
                Payment.objects.filter(pk=payment.pk).update(created_at=paid_at)
                days.add(visit_day)
        return days

    def _documents(self, patients):
        docs = [
            ("t2", PatientDocument.DocumentType.BILAN, "Bilan prénatal du 1er trimestre", 45,
             "bilan_t1_souad_el_fassi.pdf", "application/pdf",
             _lab_report_pdf("Bilan prenatal du 1er trimestre", [
                 "Groupe sanguin : O  Rhesus positif  -  RAI : negative",
                 "Hemoglobine : 12,1 g/dL   Plaquettes : 248 000 /mm3",
                 "Toxoplasmose : IgG positives, IgM negatives (immunisee)",
                 "Rubeole : immunisee  -  Syphilis (TPHA/VDRL) : negatif",
                 "VIH : negatif  -  Antigene HBs : negatif",
                 "Glycemie a jeun : 0,82 g/L  -  ECBU : sterile",
             ])),
            ("t2", PatientDocument.DocumentType.ECHOGRAPHIE, "Échographie morphologique 21 SA", 7,
             "echo_morpho_21sa.jpg", "image/jpeg", _ultrasound_jpeg()),
            ("inf", PatientDocument.DocumentType.BILAN, "Bilan hormonal J3", 18,
             "bilan_hormonal_rim_sbai.pdf", "application/pdf",
             _lab_report_pdf("Bilan hormonal a J3 du cycle", [
                 "FSH : 5,9 mUI/mL       (N : 3,5 - 12,5)",
                 "LH : 12,4 mUI/mL       (N : 2,4 - 12,6)",
                 "Oestradiol : 46 pg/mL  (N : 25 - 75)",
                 "AMH : 6,8 ng/mL        (elevee)",
                 "Prolactine : 14 ng/mL  -  TSH : 1,9 mUI/L",
                 "Testosterone totale : 0,62 ng/mL (N : 0,1 - 0,7)",
             ])),
        ]
        for key, doc_type, title, days_ago, name, content_type, payload in docs:
            exam_day = _past_day(self.day, days_ago)
            document = PatientDocument(
                cabinet=self.cabinet, patient=patients[key], title=title, document_type=doc_type,
                exam_date=exam_day, original_name=name, content_type=content_type,
                uploaded_by=self.assistant,
                consultation=Consultation.objects.filter(patient=patients[key]).order_by("-appointment__date").first(),
            )
            document.file.save(name, ContentFile(payload), save=False)
            document.save()
            PatientDocument.objects.filter(pk=document.pk).update(created_at=_aware(exam_day, time(18, 0)))

    # ── Soirée et jours suivants ─────────────────────────────────────────────

    def _evening(self, patients, start):
        first = _aware(self.day, start)
        for index, (key, reason, status, vitals) in enumerate(EVENING):
            appointment = Appointment.objects.create(
                cabinet=self.cabinet, patient=patients[key],
                date=first + timedelta(minutes=index * SLOT_MINUTES),
                duration_minutes=SLOT_MINUTES, status=status, reason=reason,
                whatsapp_status=Appointment.WhatsappStatus.CONFIRMED,
            )
            if vitals:  # constantes saisies à l'accueil par l'assistante ; fiche en brouillon
                self._consultation(patients[key], key, appointment, vitals)

    def _upcoming(self, patients):
        now = timezone.now()
        for key, offset, at, reason, wa_status, hours_ago in UPCOMING:
            Appointment.objects.create(
                cabinet=self.cabinet, patient=patients[key],
                date=_aware(self.day + timedelta(days=offset), at),
                duration_minutes=SLOT_MINUTES, status=Status.SCHEDULED, reason=reason,
                whatsapp_status=wa_status,
                whatsapp_sent_at=now - timedelta(hours=hours_ago) if hours_ago else None,
                whatsapp_sent_by=self.assistant if hours_ago else None,
            )

    # ── Caisse ───────────────────────────────────────────────────────────────

    def _closings(self, payment_days):
        """Clôture chaque journée passée encaissée ; une journée espèces du mois a un petit écart."""
        days = sorted(d for d in payment_days if d < self.day)
        month_ago = self.day - timedelta(days=30)
        gap_day = next((d for d in days if d >= month_ago
                        and expected_cash(self.cabinet, d) >= CLOSING_GAP_AMOUNT), None)
        created = 0
        for day in days:
            if CashClosing.objects.filter(cabinet=self.cabinet, date=day).exists():
                continue  # clôture réelle déjà faite : on n'y touche pas
            expected = expected_cash(self.cabinet, day)
            counted = expected - CLOSING_GAP_AMOUNT if day == gap_day else expected
            CashClosing.objects.create(
                cabinet=self.cabinet, date=day, expected_cash=expected, counted_cash=counted,
                difference=counted - expected, note=CLOSING_GAP if day == gap_day else CLOSING_OK,
                closed_by=self.assistant, closed_at=_aware(day, CLOSING_HOUR),
            )
            created += 1
        return created
