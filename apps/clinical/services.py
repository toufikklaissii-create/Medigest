import re
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import PrintProfile
from apps.common.pdf import render_pdf, save_pdf_copy

from .courriers import COURRIER_TYPES_BY_KEY

# Les trois parties de l'ordonnance : clé d'URL → (champ du formulaire, sous-titre imprimé, nom de fichier).
# Le type de document (Document.DocumentType) est résolu dans views.py pour éviter l'import circulaire.
PRESCRIPTION_PARTS = {
    "medicaments": {"field": "prescription_content", "label": "Médicaments", "subtitle": "", "file": "ordonnance"},
    "bilan": {
        "field": "bilan_content", "label": "Bilan biologique",
        "subtitle": "Bilan biologique", "file": "ordonnance_bilan",
    },
    "radiologie": {
        "field": "radiologie_content", "label": "Radiologie",
        "subtitle": "Examens radiologiques", "file": "ordonnance_radiologie",
    },
}

# Papier à en-tête du cabinet (logo, coordonnées, pied de page), posé en fond de chaque page.
LETTERHEAD = "pdf/entete_cabinet.pdf"
PRESCRIPTION_LETTERHEAD = "pdf/ordonnance_modele.pdf"  # même en-tête, titre « ORDONNANCE » imprimé

# Deux rendus par document : « Imprimer » sur papier pré-imprimé (texte seul, réglages du
# profil) ou « PDF avec en-tête » (fond du cabinet, à envoyer ou archiver).
MODE_PRINT = "impression"
MODE_LETTERHEAD = "entete"
PRINT_BASE = "pdf/_print_base.html"
LETTERHEAD_BASE = "pdf/_letterhead_base.html"
# Certificats, lettres, arrêts, hospitalisation et pré-anesthésie partagent le profil « lettre ».
LETTER_PRINT_PROFILE = PrintProfile.DocumentType.LETTRE


def free_control_candidate(consultation):
    """Dernière consultation facturée (non gratuite, non annulée) de la patiente dans le délai
    de contrôle gratuit du cabinet : {"date", "days"} ou None."""
    from apps.billing.models import Invoice

    from .models import Consultation

    cabinet = consultation.cabinet
    delay = getattr(cabinet, "controle_gratuit_jours", 0)
    if not delay or not consultation.appointment_id:
        return None
    reference = timezone.localtime(consultation.appointment.date).date()
    since = reference - timedelta(days=delay)
    previous = (
        Consultation.objects.filter(
            cabinet=cabinet, patient=consultation.patient, invoice__isnull=False, invoice__is_free=False,
            appointment__date__lt=consultation.appointment.date,
        )
        .exclude(pk=consultation.pk)
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .select_related("appointment")
        .order_by("-appointment__date")
        .first()
    )
    if previous is None:
        return None
    day = timezone.localtime(previous.appointment.date).date()
    if day < since:
        return None
    return {"date": day, "days": (reference - day).days}


# Numéro ou puce déjà tapé par la doctoresse (« 1- », « 2. », « 3) », « - », « • ») : l'ordonnance
# numérote elle-même les lignes, on l'enlève pour ne pas imprimer « 1- 1- Acide folique ».
_LEADING_MARK = re.compile(r"^(?:\d{1,2}\s*[-.)]|[-•*])\s*")


def prescription_lines(content):
    lines = (_LEADING_MARK.sub("", line.strip()) for line in (content or "").splitlines())
    return [line for line in lines if line]


def doctor_display_name(user):
    """« Dr Khadija Errmili » pour la signature des documents."""
    if user is None:
        return ""
    name = user.get_full_name().strip() or user.username
    return name if name.lower().startswith("dr") else f"Dr {name}"


def letterhead_context(patient, doc_date, doctor=None):
    """Contexte commun des documents imprimés sur le papier à en-tête du cabinet."""
    return {
        "patient": patient,
        "cabinet": patient.cabinet,
        "doc_date": doc_date,
        "doctor_name": doctor_display_name(doctor),
    }


def mode_from_request(request):
    """« ?mode=impression » : papier pré-imprimé ; sinon PDF avec en-tête."""
    return MODE_PRINT if request.GET.get("mode") == MODE_PRINT else MODE_LETTERHEAD


def render_document(template_name, context, *, cabinet, document_type, mode=MODE_LETTERHEAD,
                    background=LETTERHEAD):
    """PDF d'un document selon le profil d'impression du cabinet pour ce type.

    Impression : sans fond, sans titre, au format du profil et avec son décalage.
    En-tête : rendu habituel avec fond, réduit en A5 si le profil est en A5.
    """
    profile = PrintProfile.for_document(cabinet, document_type)
    # A5 : la page A4 est réduite de 30 % ; les gabarits grossissent leur texte pour rester lisibles.
    context = {**context, "a5": profile.format == PrintProfile.Format.A5}
    if mode == MODE_PRINT:
        return render_pdf(
            template_name, {**context, "pdf_base": PRINT_BASE, "print_mode": True},
            page_format=profile.format, offset_mm=(profile.decalage_x_mm, profile.decalage_y_mm),
        )
    return render_pdf(
        template_name, {**context, "pdf_base": LETTERHEAD_BASE}, background=background,
        page_format=profile.format,
    )


def generate_prescription_pdf(consultation, content, save_copy=True, mode=MODE_LETTERHEAD, part="medicaments"):
    """Ordonnance d'une des trois parties (médicaments, bilan biologique, radiologie), lignes numérotées."""
    patient = consultation.patient
    part_info = PRESCRIPTION_PARTS[part]
    pdf_bytes = render_document(
        "pdf/prescription.html",
        {
            "patient": patient,
            "doc_date": consultation.updated_at,
            "prescription_lines": prescription_lines(content),
            "subtitle": part_info["subtitle"],
        },
        cabinet=consultation.cabinet, document_type=PrintProfile.DocumentType.ORDONNANCE, mode=mode,
        background=PRESCRIPTION_LETTERHEAD,
    )
    if save_copy:
        save_pdf_copy(patient, part_info["file"], pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_letter_pdf(consultation, document_type, content, save_copy=True, mode=MODE_LETTERHEAD):
    patient = consultation.patient
    doc_title = COURRIER_TYPES_BY_KEY.get(document_type, {}).get("title", "Document")
    pdf_bytes = render_document(
        "pdf/letter.html",
        {
            **letterhead_context(patient, consultation.updated_at, consultation.doctor),
            "doc_title": doc_title,
            "content": content,
        },
        cabinet=consultation.cabinet, document_type=LETTER_PRINT_PROFILE, mode=mode,
    )
    if save_copy:
        save_pdf_copy(patient, document_type, pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_report_pdf(consultation, save_copy=True, mode=MODE_LETTERHEAD):
    patient = consultation.patient
    # Même calcul que le cockpit et le dossier (Consultation.pregnancy, au jour du RDV) :
    # le champ stocké gestational_age_weeks peut être périmé si la DDR a changé depuis.
    pregnancy = consultation.pregnancy
    gestational_age = f"{pregnancy['weeks']} SA + {pregnancy['days']} j" if pregnancy else None

    quick_exams = [
        line.act.name
        for line in consultation.consultation_acts.select_related("act")
        if line.act.is_quick_exam
    ]
    pdf_bytes = render_document(
        "pdf/consultation_report.html",
        {
            **letterhead_context(patient, consultation.appointment.date, consultation.doctor),
            "reason": consultation.appointment.reason,
            "blood_pressure": consultation.blood_pressure,
            "weight": consultation.weight_kg,
            "height": consultation.height_cm,
            "bmi": consultation.bmi,
            "clinical_exam": consultation.clinical_exam,
            "quick_exams": quick_exams,
            "last_menstrual_period": consultation.last_menstrual_period,
            "gestational_age": gestational_age,
            "due_date": pregnancy["due_date"] if pregnancy else None,
            "ultrasound_notes": consultation.ultrasound_notes,
            "diagnostic": consultation.diagnostic,
            "clinical_notes": consultation.clinical_notes,
        },
        cabinet=consultation.cabinet, document_type=PrintProfile.DocumentType.COMPTE_RENDU, mode=mode,
    )
    if save_copy:
        save_pdf_copy(patient, "compte_rendu", pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_patient_record_pdf(patient, save_copy=True, doctor=None):
    consultations = (
        patient.consultations.select_related("appointment")
        .order_by("-appointment__date")[:20]
    )
    pdf_bytes = render_pdf(
        "pdf/patient_record.html",
        {
            **letterhead_context(patient, timezone.now(), doctor),
            "consultations": consultations,
        },
        background=LETTERHEAD,
    )
    if save_copy:
        save_pdf_copy(patient, "dossier_patient", pdf_bytes)
    return pdf_bytes
