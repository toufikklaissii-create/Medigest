import io
import zipfile
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.patients.models import Patient

from .models import Consultation, ConsultationAct, Document, PatientDocument, pregnancy_dates
from .services import (
    LETTER_TEMPLATES,
    PRESCRIPTION_TEMPLATES,
    generate_letter_pdf,
    generate_patient_record_pdf,
    generate_prescription_pdf,
    generate_report_pdf,
)

LETTER_DOCUMENT_TYPES = {
    "letter": Document.DocumentType.LETTER,
    "certificate": Document.DocumentType.CERTIFICATE,
    "preanesthesia": Document.DocumentType.PREANESTHESIA,
}

ACTIVE_QUEUE_STATUSES = [
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _doctor_dashboard_context(request):
    cabinet = request.user.profile.cabinet
    today = timezone.localdate()
    selected_date = _parse_date(request.GET.get("date")) or today
    is_today = selected_date == today

    day_appointments = (
        Appointment.objects.filter(cabinet=cabinet, date__date=selected_date)
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("patient")
        .order_by("date")
    )

    if is_today:
        queue = day_appointments.filter(status__in=ACTIVE_QUEUE_STATUSES)
    else:
        # Statuts de file (arrivée/attente/en consultation) n'ont de sens qu'au jour J :
        # pour une autre date, on affiche tous les rendez-vous programmés de ce jour.
        queue = day_appointments

    next_patient = queue.first() if is_today else None

    return {
        "queue": queue,
        "next_patient": next_patient,
        # Patientes en salle d'attente : le client compare deux rafraîchissements pour le toast.
        "waiting_json": [
            {"id": a.pk, "name": f"{a.patient.first_name} {a.patient.last_name}"}
            for a in queue
            if a.status == Appointment.Status.WAITING
        ] if is_today else [],
        "now": timezone.now(),
        "selected_date": selected_date,
        "is_today": is_today,
        "prev_date": selected_date - timedelta(days=1),
        "next_date": selected_date + timedelta(days=1),
        "today": today,
        "today_total": day_appointments.count(),
        "in_consultation_count": day_appointments.filter(
            status=Appointment.Status.IN_CONSULTATION
        ).count(),
        "completed_today": day_appointments.filter(
            status=Appointment.Status.COMPLETED
        ).count(),
    }


@login_required
@role_required("doctor")
def doctor_dashboard(request):
    return render(request, "doctor/dashboard.html", _doctor_dashboard_context(request))


@login_required
@role_required("doctor")
def doctor_queue(request):
    """GET (HTMX, toutes les 15 s) : file d'attente + compteurs et prochaine patiente en hx-swap-oob."""
    return render(request, "doctor/_queue.html", _doctor_dashboard_context(request))


def _apply_consultation_post(request, consultation, cabinet):
    """Copie les champs de la fiche (POST) sur la consultation, sans toucher au statut ni sauvegarder."""
    consultation.clinical_exam = request.POST.get("clinical_exam", "")
    consultation.clinical_notes = request.POST.get("clinical_notes", "")
    consultation.diagnostic = request.POST.get("diagnostic", "")
    pregnancy = consultation.pregnancy
    consultation.gestational_age_weeks = pregnancy["weeks"] if pregnancy else None
    consultation.ultrasound_notes = request.POST.get("ultrasound_notes", "")
    if not consultation.doctor_id:
        consultation.doctor = request.user

    act_ids = [int(v) for v in request.POST.getlist("acts") if v]
    selected_acts = MedicalAct.objects.filter(cabinet=cabinet, id__in=act_ids)

    consultation.consultation_acts.exclude(act_id__in=act_ids).delete()
    existing_act_ids = set(consultation.consultation_acts.values_list("act_id", flat=True))
    for act in selected_acts:
        if act.id not in existing_act_ids:
            ConsultationAct.objects.create(consultation=consultation, act=act, price=act.price)

    prescription_content = request.POST.get("prescription_content", "").strip()
    if prescription_content:
        Document.objects.update_or_create(
            consultation=consultation,
            document_type=Document.DocumentType.PRESCRIPTION,
            defaults={"content": prescription_content},
        )

    letter_type = request.POST.get("letter_type", "")
    letter_content = request.POST.get("letter_content", "").strip()
    if letter_content and letter_type in LETTER_DOCUMENT_TYPES:
        Document.objects.update_or_create(
            consultation=consultation,
            document_type=LETTER_DOCUMENT_TYPES[letter_type],
            defaults={"content": letter_content},
        )


@login_required
@role_required("doctor")
def consultation_detail(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"),
        pk=appointment_id,
        cabinet=cabinet,
    )
    consultation, _ = Consultation.objects.get_or_create(
        appointment=appointment,
        defaults={"patient": appointment.patient, "doctor": request.user, "cabinet": cabinet},
    )

    if request.method == "POST":
        action = request.POST.get("action")
        _apply_consultation_post(request, consultation, cabinet)

        consultation.status = (
            Consultation.Status.VALIDATED if action == "validate" else Consultation.Status.DRAFT
        )
        consultation.save()

        if action == "validate":
            appointment.status = Appointment.Status.COMPLETED
            appointment.save(update_fields=["status"])
            messages.success(
                request,
                f"Consultation validée et facture {consultation.invoice.invoice_number} transmise.",
            )
            return redirect("clinical:doctor_dashboard")

        messages.success(request, "Brouillon enregistré.")
        return redirect("clinical:consultation_detail", appointment_id=appointment.pk)

    all_acts = MedicalAct.objects.filter(cabinet=cabinet, is_active=True)
    selected_act_ids = list(
        consultation.consultation_acts.values_list("act_id", flat=True)
    )
    acts_json = [
        {
            "id": act.id,
            "code": act.code,
            "name": act.name,
            "price": float(act.price),
            "is_quick_exam": act.is_quick_exam,
        }
        for act in all_acts
    ]
    prescription_doc = consultation.documents.filter(
        document_type=Document.DocumentType.PRESCRIPTION
    ).first()
    prescription_templates_json = [
        {"key": key, "label": tpl["label"], "text": tpl["text"]}
        for key, tpl in PRESCRIPTION_TEMPLATES.items()
    ]
    letter_templates_json = [
        {"key": key, "label": tpl["label"], "text": tpl["text"]}
        for key, tpl in LETTER_TEMPLATES.items()
    ]
    letters_by_type = {
        doc.document_type: doc.content
        for doc in consultation.documents.filter(
            document_type__in=LETTER_DOCUMENT_TYPES.values()
        )
    }
    letters_json = {
        key: letters_by_type.get(doc_type, "")
        for key, doc_type in LETTER_DOCUMENT_TYPES.items()
    }
    patient_documents = PatientDocument.objects.filter(
        cabinet=cabinet, patient=appointment.patient
    )
    previous_consultations = (
        Consultation.objects.filter(cabinet=cabinet, patient=appointment.patient)
        .exclude(pk=consultation.pk)
        .select_related("appointment")
        .order_by("-appointment__date")[:3]
    )
    return render(
        request,
        "doctor/consultation.html",
        {
            "appointment": appointment,
            "patient": appointment.patient,
            "consultation": consultation,
            "bmi": consultation.bmi,
            "pregnancy": consultation.pregnancy,
            "all_acts": all_acts,
            "selected_act_ids": selected_act_ids,
            "acts_json": acts_json,
            "prescription_content": prescription_doc.content if prescription_doc else "",
            "prescription_templates_json": prescription_templates_json,
            "letter_templates_json": letter_templates_json,
            "letters_json": letters_json,
            "patient_documents": patient_documents,
            "document_type_choices": PatientDocument.DocumentType.choices,
            "previous_consultations": previous_consultations,
        },
    )


@login_required
@role_required("doctor")
@require_POST
def autosave_consultation(request, appointment_id):
    """Sauvegarde silencieuse (HTMX) de la fiche : ne change jamais le statut de la consultation."""
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation, _ = Consultation.objects.get_or_create(
        appointment=appointment,
        defaults={"patient": appointment.patient, "doctor": request.user, "cabinet": cabinet},
    )
    _apply_consultation_post(request, consultation, cabinet)
    # update_fields exclut `status` : une autosave en vol ne peut pas annuler une validation concurrente.
    consultation.save(
        update_fields=[
            "clinical_exam", "clinical_notes", "diagnostic", "gestational_age_weeks",
            "ultrasound_notes", "doctor", "updated_at",
        ]
    )
    return HttpResponse(status=204)


LETTER_LABELS = {
    Document.DocumentType.LETTER: ("letter", "Lettre à un confrère"),
    Document.DocumentType.CERTIFICATE: ("certificate", "Certificat de prise en charge"),
    Document.DocumentType.PREANESTHESIA: ("preanesthesia", "Consultation pré-anesthésie"),
}


@login_required
@role_required("doctor")
def patient_file(request, patient_id):
    """Dossier patiente (lecture seule) : historique des visites, évolution, documents, factures."""
    cabinet = request.user.profile.cabinet
    patient = get_object_or_404(Patient, pk=patient_id, cabinet=cabinet)

    consultations = list(
        Consultation.objects.filter(cabinet=cabinet, patient=patient)
        .select_related("appointment", "invoice")
        .prefetch_related("consultation_acts__act", "documents")
        .order_by("-appointment__date", "-pk")
    )
    for consultation in consultations:
        documents = {doc.document_type: doc for doc in consultation.documents.all()}
        prescription = documents.get(Document.DocumentType.PRESCRIPTION)
        consultation.prescription = prescription.content if prescription else ""
        consultation.letters = [
            (key, label) for doc_type, (key, label) in LETTER_LABELS.items()
            if doc_type in documents and documents[doc_type].content
        ]
        # `acts` est le M2M du modèle : les lignes chargées vivent dans `act_lines`.
        consultation.act_lines = list(consultation.consultation_acts.all())
        consultation.quick_exams = [ca for ca in consultation.act_lines if ca.act.is_quick_exam]
        consultation.acts_total = sum((ca.price for ca in consultation.act_lines), 0)
        consultation.term = consultation.pregnancy

    # Bandeau grossesse : DDR la plus récente, terme recalculé à aujourd'hui (None si hors grossesse).
    latest_lmp = next((c.last_menstrual_period for c in consultations if c.last_menstrual_period), None)
    pregnancy = pregnancy_dates(latest_lmp, timezone.localdate())

    return render(
        request,
        "doctor/patient_file.html",
        {
            "patient": patient,
            "consultations": consultations,
            "pregnancy": pregnancy,
            "documents": PatientDocument.objects.filter(cabinet=cabinet, patient=patient),
            "document_type_choices": PatientDocument.DocumentType.choices,
            "invoices": Invoice.objects.filter(cabinet=cabinet, patient=patient).order_by("-created_at"),
        },
    )


@login_required
@role_required("doctor")
def upload_patient_document(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    if request.method == "POST" and request.FILES.get("file"):
        title = request.POST.get("title", "").strip() or request.FILES["file"].name
        document_type = request.POST.get("document_type", PatientDocument.DocumentType.AUTRE)
        if document_type not in PatientDocument.DocumentType.values:
            document_type = PatientDocument.DocumentType.AUTRE
        PatientDocument.objects.create(
            cabinet=cabinet,
            patient=appointment.patient,
            title=title,
            document_type=document_type,
            file=request.FILES["file"],
        )
        messages.success(request, "Document ajouté au dossier de la patiente.")
    else:
        messages.error(request, "Veuillez sélectionner un fichier à téléverser.")
    return redirect("clinical:consultation_detail", appointment_id=appointment.pk)


@login_required
@role_required("doctor")
def download_patient_record_pdf(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"), pk=appointment_id, cabinet=cabinet
    )
    pdf_bytes = generate_patient_record_pdf(appointment.patient)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="dossier_{appointment.patient.patient_number}.pdf"'
    )
    return response


@login_required
@role_required("doctor")
def download_full_patient_archive(request, patient_id):
    """ZIP contenant le PDF récapitulatif du dossier + tous les documents joints (radios/bilans)."""
    cabinet = request.user.profile.cabinet
    patient = get_object_or_404(Patient, pk=patient_id, cabinet=cabinet)

    pdf_bytes = generate_patient_record_pdf(patient, save_copy=False)
    documents = PatientDocument.objects.filter(cabinet=cabinet, patient=patient)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("patient_record.pdf", pdf_bytes)
        used_names = set()
        for doc in documents:
            if not doc.file:
                continue
            base_name = doc.file.name.rsplit("/", 1)[-1]
            arcname = f"documents/{base_name}"
            suffix = 1
            while arcname in used_names:
                stem, _, ext = base_name.rpartition(".")
                arcname = f"documents/{stem or base_name}_{suffix}{'.' + ext if ext else ''}"
                suffix += 1
            used_names.add(arcname)
            doc.file.open("rb")
            try:
                archive.writestr(arcname, doc.file.read())
            finally:
                doc.file.close()

    slug = slugify(f"{patient.first_name}-{patient.last_name}") or patient.patient_number
    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="Dossier_{slug}.zip"'
    return response


@login_required
@role_required("doctor")
def download_prescription_pdf(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation = get_object_or_404(Consultation, appointment=appointment, cabinet=cabinet)
    prescription_doc = consultation.documents.filter(
        document_type=Document.DocumentType.PRESCRIPTION
    ).first()
    content = prescription_doc.content if prescription_doc else ""
    pdf_bytes = generate_prescription_pdf(consultation, content)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="ordonnance_{consultation.patient.patient_number}.pdf"'
    return response


@login_required
@role_required("doctor")
def download_letter_pdf(request, appointment_id, letter_type):
    if letter_type not in LETTER_DOCUMENT_TYPES:
        raise Http404("Type de document inconnu.")
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation = get_object_or_404(Consultation, appointment=appointment, cabinet=cabinet)
    letter_doc = consultation.documents.filter(
        document_type=LETTER_DOCUMENT_TYPES[letter_type]
    ).first()
    content = letter_doc.content if letter_doc else ""
    pdf_bytes = generate_letter_pdf(consultation, letter_type, content)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{letter_type}_{consultation.patient.patient_number}.pdf"'
    )
    return response


@login_required
@role_required("doctor")
def download_report_pdf(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation = get_object_or_404(Consultation, appointment=appointment, cabinet=cabinet)
    pdf_bytes = generate_report_pdf(consultation)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="compte_rendu_{consultation.patient.patient_number}.pdf"'
    return response
