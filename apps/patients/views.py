import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core import signing
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical.documents import (
    PHONE_LINK_MAX_AGE,
    consultation_for,
    documents_context,
    make_phone_token,
    parse_exam_date,
    qr_svg,
    read_phone_token,
    save_documents,
)
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
            "is_doctor": request.user.profile.role == "doctor",
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
                allergies=request.POST.get("allergies", "").strip(),
                medical_history=request.POST.get("medical_history", "").strip(),
            )
            messages.success(request, f"Patiente {patient.full_name} créée ({patient.patient_number}).")
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
            patient.allergies = request.POST.get("allergies", "").strip()
            patient.medical_history = request.POST.get("medical_history", "").strip()
            patient.save()
            messages.success(request, f"Dossier de {patient.full_name} mis à jour.")
            return redirect("patients:index")
        messages.error(request, "Nom et prénom sont obligatoires.")

    return render(request, "patients/edit.html", {"patient": patient})


@login_required
def patient_documents(request, pk):
    cabinet = request.user.profile.cabinet
    patient = get_object_or_404(Patient, pk=pk, cabinet=cabinet)
    if request.method == "POST":
        created, errors = save_documents(
            request.FILES.getlist("files") + request.FILES.getlist("file"),
            cabinet=cabinet,
            patient=patient,
            document_type=request.POST.get("document_type", ""),
            exam_date=parse_exam_date(request.POST.get("exam_date")) or timezone.localdate(),
            consultation=consultation_for(cabinet, patient, request.POST.get("consultation")),
            uploaded_by=request.user,
            title=request.POST.get("title", "").strip(),
        )
        success = None
        if created:
            success = ("Document ajouté au dossier de la patiente." if len(created) == 1
                       else f"{len(created)} documents ajoutés au dossier de la patiente.")

        if request.htmx:
            context = documents_context(request, patient)
            response = render(request, "patients/_documents_panel.html", context)
            toast = {"message": " ".join(errors), "type": "error"} if errors else {"message": success, "type": "success"}
            response.headers["HX-Trigger"] = json.dumps(
                {"toast": toast, "documents-changed": {"count": context["documents"].count()}}
            )
            return response

        for error in errors:
            messages.error(request, error)
        if success:
            messages.success(request, success)
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(next_url)
        return redirect("patients:patient_documents", pk=patient.pk)

    context = documents_context(request, patient)
    if request.htmx:
        # Rafraîchissement du panneau (ex. pendant l'affichage du QR code « téléphone »).
        response = render(request, "patients/_documents_panel.html", context)
        response.headers["HX-Trigger"] = json.dumps({"documents-changed": {"count": context["documents"].count()}})
        return response
    return render(request, "patients/documents.html", context)


def _phone_base_url(request):
    """Le téléphone doit joindre le serveur : PUBLIC_BASE_URL (IP du poste sur le Wi-Fi) si défini."""
    base = getattr(settings, "PUBLIC_BASE_URL", "")
    return base.rstrip("/") if base else request.build_absolute_uri("/").rstrip("/")


@login_required
def phone_upload_qr(request, pk):
    """Panneau QR code : lien signé 15 min, une patiente, upload uniquement."""
    patient = get_object_or_404(Patient, pk=pk, cabinet=request.user.profile.cabinet)
    token = make_phone_token(patient, request.user)
    link = _phone_base_url(request) + reverse("patients:phone_upload", args=[token])
    return render(
        request,
        "patients/_phone_qr.html",
        {
            "patient": patient,
            "link": link,
            "qr_svg": mark_safe(qr_svg(link)),
            "expires_at": timezone.localtime() + timedelta(seconds=PHONE_LINK_MAX_AGE),
            "max_age_minutes": PHONE_LINK_MAX_AGE // 60,
        },
    )


def phone_upload(request, token):
    """Page mobile sans connexion : choix du type, photo/fichier, envoi. Aucune lecture du dossier."""
    try:
        payload = read_phone_token(token)
    except signing.SignatureExpired:
        return render(request, "patients/phone_upload.html", {"state": "expired"}, status=410)
    except signing.BadSignature:
        return render(request, "patients/phone_upload.html", {"state": "invalid"}, status=404)

    patient = Patient.objects.filter(pk=payload.get("p"), cabinet_id=payload.get("c")).select_related("cabinet").first()
    if patient is None:
        return render(request, "patients/phone_upload.html", {"state": "invalid"}, status=404)

    context = {
        "state": "form",
        "patient_label": f"{patient.first_name} {patient.last_name[:1]}.".strip(),
        "cabinet": patient.cabinet,
        "document_type_choices": PatientDocument.DocumentType.choices,
        "today": timezone.localdate(),
    }
    if request.method == "POST":
        created, errors = save_documents(
            request.FILES.getlist("files"),
            cabinet=patient.cabinet,
            patient=patient,
            document_type=request.POST.get("document_type", ""),
            exam_date=parse_exam_date(request.POST.get("exam_date")) or timezone.localdate(),
            uploaded_by=User.objects.filter(pk=payload.get("u")).first(),
        )
        context.update({"errors": errors, "sent_count": len(created)})
        if created:
            context["state"] = "sent"
        return render(request, "patients/phone_upload.html", context, status=200 if created else 400)
    return render(request, "patients/phone_upload.html", context)
