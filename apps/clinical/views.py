import io
import zipfile
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.decorators import role_required
from apps.appointments.models import Appointment
from apps.billing.models import MedicalAct
from apps.patients.models import Patient

from .models import Consultation, ConsultationAct, Document, PatientDocument
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


@login_required
@role_required("doctor")
def doctor_dashboard(request):
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

    return render(
        request,
        "doctor/dashboard.html",
        {
            "queue": queue,
            "next_patient": next_patient,
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
        },
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
