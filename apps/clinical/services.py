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
