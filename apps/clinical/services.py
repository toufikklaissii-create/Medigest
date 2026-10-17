from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import PrintProfile
from apps.common.pdf import render_pdf, save_pdf_copy

PRESCRIPTION_TEMPLATES = {
    "grossesse_t1_t2": {
        "label": "Suivi Grossesse T1/T2",
        "text": (
            "Acide folique 0,4 mg — 1 comprimé par jour\n"
            "Supplémentation vitamino-calcique — 1 comprimé par jour pendant 1 mois\n"
            "Repos relatif, hydratation abondante\n"
            "Échographie de datation/morphologique à programmer selon le terme"
        ),
    },
    "infection_gyneco": {
        "label": "Infection gynécologique",
        "text": (
            "Ovules antifongiques — 1 ovule au coucher pendant 3 jours\n"
            "Toilette intime avec savon à pH neutre, 2 fois par jour\n"
            "Éviter les rapports pendant le traitement\n"
            "Consultation de contrôle dans 2 semaines si persistance des symptômes"
        ),
    },
    "bilan_preconceptionnel": {
        "label": "Bilan préconceptionnel",
        "text": (
            "NFS, glycémie à jeun, groupe sanguin et rhésus\n"
            "Sérologies : toxoplasmose, rubéole, syphilis, VIH, hépatites B et C\n"
            "TSH, frottis cervico-vaginal si non à jour\n"
            "Acide folique 0,4 mg — 1 comprimé par jour dès le désir de grossesse"
        ),
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
# Lettre, certificat et pré-anesthésie partagent le profil « lettre ».
LETTER_PRINT_PROFILE = PrintProfile.DocumentType.LETTRE


LETTER_TEMPLATES = {
    "letter": {
        "label": "Lettre à un confrère",
        "text": (
            "Cher confrère, chère consœur,\n\n"
            "Je vous adresse Madame [Nom de la patiente] pour avis complémentaire concernant sa prise en charge gynécologique/obstétricale.\n\n"
            "Éléments cliniques : [à compléter]\n\n"
            "Je reste à votre disposition pour tout échange complémentaire.\n\n"
            "Confraternellement,\nDr ERRMILI Khadija"
        ),
    },
    "certificate": {
        "label": "Certificat de prise en charge",
        "text": (
            "Je soussignée, Dr ERRMILI Khadija, certifie que Madame [Nom de la patiente] est prise en charge "
            "dans le cadre d'un suivi gynécologique/obstétrical au sein de ce cabinet.\n\n"
            "Ce certificat est délivré à la patiente pour faire valoir ce que de droit."
        ),
    },
    "preanesthesia": {
        "label": "Consultation pré-anesthésie",
        "text": (
            "Compte rendu à l'attention du médecin anesthésiste dans le cadre d'une consultation pré-anesthésique.\n\n"
            "Antécédents médicaux : [à compléter]\n"
            "Allergies connues : [à compléter]\n"
            "Traitement en cours : [à compléter]\n\n"
            "Intervention prévue : [à compléter]"
        ),
    },
}


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


def prescription_lines(content):
    return [line.strip() for line in (content or "").splitlines() if line.strip()]


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
    if mode == MODE_PRINT:
        return render_pdf(
            template_name, {**context, "pdf_base": PRINT_BASE, "print_mode": True},
            page_format=profile.format, offset_mm=(profile.decalage_x_mm, profile.decalage_y_mm),
        )
    return render_pdf(
        template_name, {**context, "pdf_base": LETTERHEAD_BASE}, background=background,
        page_format=profile.format,
    )


def generate_prescription_pdf(consultation, content, save_copy=True, mode=MODE_LETTERHEAD):
    patient = consultation.patient
    pdf_bytes = render_document(
        "pdf/prescription.html",
        {
            "patient": patient,
            "doc_date": consultation.updated_at,
            "prescription_lines": prescription_lines(content),
        },
        cabinet=consultation.cabinet, document_type=PrintProfile.DocumentType.ORDONNANCE, mode=mode,
        background=PRESCRIPTION_LETTERHEAD,
    )
    if save_copy:
        save_pdf_copy(patient, "ordonnance", pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_letter_pdf(consultation, document_type, content, save_copy=True, mode=MODE_LETTERHEAD):
    patient = consultation.patient
    doc_title = LETTER_TEMPLATES.get(document_type, {}).get("label", "Document")
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
