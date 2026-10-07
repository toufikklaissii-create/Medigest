from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical.models import Consultation, PatientDocument

from .models import Patient


@login_required
def index(request):
    cabinet = request.user.profile.cabinet
    patients = list(Patient.objects.filter(cabinet=cabinet)[:50])
    upcoming = (
        Appointment.objects.select_related("patient")
        .filter(cabinet=cabinet, patient__in=patients, date__gte=timezone.now())
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )
    next_appointment_by_patient = {}
    for appt in upcoming:
        next_appointment_by_patient.setdefault(appt.patient_id, appt)

    completed_consultations = (
        Consultation.objects.select_related("appointment")
        .filter(cabinet=cabinet, patient__in=patients, status=Consultation.Status.VALIDATED)
        .order_by("-created_at")
    )
    last_completed_by_patient = {}
    for consultation in completed_consultations:
        last_completed_by_patient.setdefault(consultation.patient_id, consultation)

    for patient in patients:
        patient.next_appointment = next_appointment_by_patient.get(patient.pk)
        patient.last_completed_consultation = last_completed_by_patient.get(patient.pk)

    view_filter = request.GET.get("view", "all")
    if view_filter == "completed":
        patients = [p for p in patients if p.last_completed_consultation]

    return render(
        request,
        "patients/index.html",
        {
            "patients": patients,
            "view_filter": view_filter,
            "completed_count": len(last_completed_by_patient),
        },
    )


@login_required
def create_patient(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if first_name and last_name:
            patient = Patient.objects.create(
                cabinet=request.user.profile.cabinet,
                first_name=first_name,
                last_name=last_name,
                cin=request.POST.get("cin", "").strip(),
                social_security_number=request.POST.get("social_security_number", "").strip(),
                organisme_social=request.POST.get("organisme_social", "").strip(),
                birth_date=request.POST.get("birth_date") or None,
                phone=request.POST.get("phone", "").strip(),
                emergency_contact=request.POST.get("emergency_contact", "").strip(),
                blood_group=request.POST.get("blood_group", "").strip(),
            )
            messages.success(request, f"Patiente {patient} créée ({patient.patient_number}).")
            return redirect("appointments:create_appointment_for", patient_id=patient.pk)
        messages.error(request, "Nom et prénom sont obligatoires.")

    return render(request, "patients/create.html")


@login_required
def edit_patient(request, pk):
    patient = get_object_or_404(Patient, pk=pk, cabinet=request.user.profile.cabinet)
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if first_name and last_name:
            patient.first_name = first_name
            patient.last_name = last_name
            patient.cin = request.POST.get("cin", "").strip()
            patient.social_security_number = request.POST.get("social_security_number", "").strip()
            patient.organisme_social = request.POST.get("organisme_social", "").strip()
            patient.birth_date = request.POST.get("birth_date") or None
            patient.phone = request.POST.get("phone", "").strip()
            patient.emergency_contact = request.POST.get("emergency_contact", "").strip()
            patient.blood_group = request.POST.get("blood_group", "").strip()
            patient.save()
            messages.success(request, f"Dossier de {patient} mis à jour.")
            return redirect("patients:index")
        messages.error(request, "Nom et prénom sont obligatoires.")

    return render(request, "patients/edit.html", {"patient": patient})


@login_required
def patient_documents(request, pk):
    patient = get_object_or_404(Patient, pk=pk, cabinet=request.user.profile.cabinet)
    if request.method == "POST" and request.FILES.get("file"):
        title = request.POST.get("title", "").strip() or request.FILES["file"].name
        document_type = request.POST.get("document_type", PatientDocument.DocumentType.AUTRE)
        if document_type not in PatientDocument.DocumentType.values:
            document_type = PatientDocument.DocumentType.AUTRE
        PatientDocument.objects.create(
            cabinet=request.user.profile.cabinet,
            patient=patient,
            title=title,
            document_type=document_type,
            file=request.FILES["file"],
        )
        messages.success(request, "Document ajouté au dossier de la patiente.")
        return redirect("patients:patient_documents", pk=patient.pk)

    documents = PatientDocument.objects.filter(cabinet=request.user.profile.cabinet, patient=patient)
    return render(
        request,
        "patients/documents.html",
        {
            "patient": patient,
            "documents": documents,
            "document_type_choices": PatientDocument.DocumentType.choices,
        },
    )
