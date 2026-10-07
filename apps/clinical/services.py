from django.utils import timezone

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


def prescription_lines(content):
    return [line.strip() for line in (content or "").splitlines() if line.strip()]


def generate_prescription_pdf(consultation, content, save_copy=True):
    patient = consultation.patient
    pdf_bytes = render_pdf(
        "pdf/prescription.html",
        {
            "patient": patient,
            "doc_date": consultation.updated_at,
            "prescription_lines": prescription_lines(content),
        },
    )
    if save_copy:
        save_pdf_copy(patient, "ordonnance", pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_letter_pdf(consultation, document_type, content, save_copy=True):
    patient = consultation.patient
    doc_title = LETTER_TEMPLATES.get(document_type, {}).get("label", "Document")
    pdf_bytes = render_pdf(
        "pdf/letter.html",
        {
            "patient": patient,
            "doc_date": consultation.updated_at,
            "doc_title": doc_title,
            "content": content,
        },
    )
    if save_copy:
        save_pdf_copy(patient, document_type, pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_report_pdf(consultation, save_copy=True):
    patient = consultation.patient
    gestational_age = None
    if consultation.gestational_age_weeks is not None:
        gestational_age = f"{consultation.gestational_age_weeks} SA"

    pdf_bytes = render_pdf(
        "pdf/consultation_report.html",
        {
            "patient": patient,
            "doc_date": consultation.updated_at,
            "reason": consultation.appointment.reason,
            "last_menstrual_period": consultation.last_menstrual_period,
            "gestational_age": gestational_age,
            "ultrasound_notes": consultation.ultrasound_notes,
            "diagnostic": consultation.diagnostic,
            "clinical_notes": consultation.clinical_notes,
        },
    )
    if save_copy:
        save_pdf_copy(patient, "compte_rendu", pdf_bytes, reference=consultation.pk)
    return pdf_bytes


def generate_patient_record_pdf(patient, save_copy=True):
    consultations = (
        patient.consultations.select_related("appointment")
        .order_by("-created_at")[:20]
    )
    pdf_bytes = render_pdf(
        "pdf/patient_record.html",
        {
            "patient": patient,
            "doc_date": timezone.now(),
            "consultations": consultations,
        },
    )
    if save_copy:
        save_pdf_copy(patient, "dossier_patient", pdf_bytes)
    return pdf_bytes
