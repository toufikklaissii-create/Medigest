from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.decorators import role_required
from apps.appointments.models import Appointment
from apps.billing.models import MedicalAct

from .models import Consultation, ConsultationAct, Document
from .services import (
    PRESCRIPTION_TEMPLATES,
    generate_prescription_pdf,
    generate_report_pdf,
)

ACTIVE_QUEUE_STATUSES = [
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
]


@login_required
@role_required("doctor")
def doctor_dashboard(request):
    today = timezone.localdate()
    today_appointments = Appointment.objects.filter(date__date=today).exclude(
        status=Appointment.Status.CANCELLED
    )
    queue = (
        today_appointments.select_related("patient")
        .filter(status__in=ACTIVE_QUEUE_STATUSES)
        .order_by("date")
    )
    next_patient = queue.first()
    return render(
        request,
        "doctor/dashboard.html",
        {
            "queue": queue,
            "next_patient": next_patient,
            "now": timezone.now(),
            "today_total": today_appointments.count(),
            "in_consultation_count": queue.filter(
                status=Appointment.Status.IN_CONSULTATION
            ).count(),
            "completed_today": today_appointments.filter(
                status=Appointment.Status.COMPLETED
            ).count(),
        },
    )


@login_required
@role_required("doctor")
def consultation_detail(request, appointment_id):
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"), pk=appointment_id
    )
    consultation, _ = Consultation.objects.get_or_create(
        appointment=appointment,
        defaults={"patient": appointment.patient, "doctor": request.user},
    )

    if request.method == "POST":
        action = request.POST.get("action")

        consultation.blood_pressure = request.POST.get("blood_pressure", "")
        weight = request.POST.get("weight_kg") or None
        consultation.weight_kg = weight
        consultation.clinical_notes = request.POST.get("clinical_notes", "")
        consultation.diagnostic = request.POST.get("diagnostic", "")
        consultation.last_menstrual_period = request.POST.get("last_menstrual_period") or None
        ga_weeks = request.POST.get("gestational_age_weeks") or None
        consultation.gestational_age_weeks = int(ga_weeks) if ga_weeks else None
        consultation.ultrasound_notes = request.POST.get("ultrasound_notes", "")
        if not consultation.doctor_id:
            consultation.doctor = request.user

        act_ids = [int(v) for v in request.POST.getlist("acts") if v]
        selected_acts = MedicalAct.objects.filter(id__in=act_ids)

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

    all_acts = MedicalAct.objects.filter(is_active=True)
    selected_act_ids = list(
        consultation.consultation_acts.values_list("act_id", flat=True)
    )
    acts_json = [
        {"id": act.id, "code": act.code, "name": act.name, "price": float(act.price)}
        for act in all_acts
    ]
    prescription_doc = consultation.documents.filter(
        document_type=Document.DocumentType.PRESCRIPTION
    ).first()
    prescription_templates_json = [
        {"key": key, "label": tpl["label"], "text": tpl["text"]}
        for key, tpl in PRESCRIPTION_TEMPLATES.items()
    ]
    return render(
        request,
        "doctor/consultation.html",
        {
            "appointment": appointment,
            "patient": appointment.patient,
            "consultation": consultation,
            "all_acts": all_acts,
            "selected_act_ids": selected_act_ids,
            "acts_json": acts_json,
            "prescription_content": prescription_doc.content if prescription_doc else "",
            "prescription_templates_json": prescription_templates_json,
        },
    )


@login_required
@role_required("doctor")
def download_prescription_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    consultation = get_object_or_404(Consultation, appointment=appointment)
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
def download_report_pdf(request, appointment_id):
    appointment = get_object_or_404(Appointment, pk=appointment_id)
    consultation = get_object_or_404(Consultation, appointment=appointment)
    pdf_bytes = generate_report_pdf(consultation)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="compte_rendu_{consultation.patient.patient_number}.pdf"'
    return response
