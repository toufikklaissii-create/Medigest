import io
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.accounts.models import CLINICIAN_ROLES
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, MedicalAct
from apps.billing.services import parse_amount
from apps.patients.models import Patient

from .courriers import COURRIER_TYPES, remplir, valeurs_champs
from .documents import documents_context, parse_exam_date, save_documents
from .models import (
    Consultation, ConsultationAct, Document, ModeleCourrier, ModeleOrdonnance, PatientDocument, pregnancy_dates,
)
from .services import (
    PRESCRIPTION_PARTS,
    doctor_display_name,
    generate_letter_pdf,
    generate_patient_record_pdf,
    generate_prescription_pdf,
    free_control_candidate,
    generate_report_pdf,
    mode_from_request,
)

# Certificats et courriers : la clé d'URL est aussi le type de document en base (voir courriers.py).
LETTER_DOCUMENT_TYPES = {t["key"]: t["key"] for t in COURRIER_TYPES}

# Les trois parties de l'ordonnance et leur document en base (l'ancienne ordonnance = médicaments).
PART_DOCUMENT_TYPES = {
    "medicaments": Document.DocumentType.PRESCRIPTION,
    "bilan": Document.DocumentType.BILAN_BIOLOGIQUE,
    "radiologie": Document.DocumentType.RADIOLOGIE,
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
@role_required(*CLINICIAN_ROLES)
def doctor_dashboard(request):
    return render(request, "doctor/dashboard.html", _doctor_dashboard_context(request))


@login_required
@role_required(*CLINICIAN_ROLES)
def doctor_queue(request):
    """GET (HTMX, toutes les 15 s) : file d'attente + compteurs et prochaine patiente en hx-swap-oob."""
    return render(request, "doctor/_queue.html", _doctor_dashboard_context(request))


def _apply_consultation_post(request, consultation, cabinet):
    """Copie les champs de la fiche (POST) sur la consultation, sans toucher au statut ni sauvegarder.

    Renvoie les libellés des actes en prix libre sélectionnés sans prix (validation refusée).
    """
    consultation.clinical_exam = request.POST.get("clinical_exam", "")
    consultation.clinical_notes = request.POST.get("clinical_notes", "")
    consultation.diagnostic = request.POST.get("diagnostic", "")
    pregnancy = consultation.pregnancy
    consultation.gestational_age_weeks = pregnancy["weeks"] if pregnancy else None
    consultation.ultrasound_notes = request.POST.get("ultrasound_notes", "")
    sees_money = request.user.profile.sees_money
    if not consultation.doctor_id or (
        request.user.profile.is_remplacant and consultation.status == Consultation.Status.DRAFT
    ):
        # Le remplaçant qui consulte signe les documents de cette consultation.
        consultation.doctor = request.user

    act_ids = [int(v) for v in request.POST.getlist("acts") if v]
    selected_acts = MedicalAct.objects.filter(cabinet=cabinet, id__in=act_ids)

    had_lines = consultation.consultation_acts.exists()
    consultation.consultation_acts.exclude(act_id__in=act_ids).delete()
    lines = {line.act_id: line for line in consultation.consultation_acts.all()}
    missing_prices = []
    for act in selected_acts:
        # Prix de la ligne fixé par la doctoresse, pré-rempli au tarif du catalogue.
        price = parse_amount(request.POST.get(f"price_{act.id}"))
        if not sees_money and not act.prix_libre:
            # Remplaçant : aucun prix modifiable, sauf le montant d'un acte en prix libre.
            price = None
        if act.prix_libre and (price is None or price <= 0):
            # Prix libre : jamais de tarif par défaut. Ligne gardée à 0 (brouillon), validation refusée.
            missing_prices.append(act.name)
            price = Decimal("0")
        elif price is None or price < 0:
            price = lines[act.id].price if act.id in lines else act.price
        if act.id not in lines:
            ConsultationAct.objects.create(consultation=consultation, act=act, price=price)
        elif lines[act.id].price != price:
            ConsultationAct.objects.filter(pk=lines[act.id].pk).update(price=price)

    if sees_money:
        discount = parse_amount(request.POST.get("billing_discount"))
        consultation.billing_discount = discount if discount and discount > 0 else 0
        consultation.billing_free = request.POST.get("billing_free") == "on"
    elif not had_lines and not consultation.billing_free and consultation.status == Consultation.Status.DRAFT:
        # Remplaçant : remise et gratuité ne sont pas modifiables ; le contrôle gratuit
        # s'applique comme la case pré-cochée qu'aurait vue la doctoresse.
        consultation.billing_free = bool(free_control_candidate(consultation))

    for part, document_type in PART_DOCUMENT_TYPES.items():
        field = PRESCRIPTION_PARTS[part]["field"]
        if field not in request.POST:
            continue
        content = request.POST.get(field, "").strip()
        if content:
            Document.objects.update_or_create(
                consultation=consultation, document_type=document_type, defaults={"content": content},
            )
        else:
            # Partie vidée par la doctoresse : on garde la ligne mais sans contenu (rien à imprimer).
            consultation.documents.filter(document_type=document_type).update(content="")

    # Fiche de consultation : les 6 certificats/courriers arrivent ensemble (champs courrier_<type>).
    for key, document_type in LETTER_DOCUMENT_TYPES.items():
        field = f"courrier_{key}"
        if field not in request.POST:
            continue
        content = request.POST.get(field, "").strip()
        if content:
            Document.objects.update_or_create(
                consultation=consultation, document_type=document_type, defaults={"content": content},
            )
        else:
            consultation.documents.filter(document_type=document_type).update(content="")

    # Ancien envoi (un seul courrier à la fois) : toujours accepté.
    letter_type = request.POST.get("letter_type", "")
    letter_content = request.POST.get("letter_content", "").strip()
    if letter_content and letter_type in LETTER_DOCUMENT_TYPES:
        Document.objects.update_or_create(
            consultation=consultation,
            document_type=LETTER_DOCUMENT_TYPES[letter_type],
            defaults={"content": letter_content},
        )
    return missing_prices


def _prescription_contents(consultation):
    """{"medicaments": texte, "bilan": texte, "radiologie": texte} de la consultation."""
    by_type = dict(
        consultation.documents.filter(document_type__in=PART_DOCUMENT_TYPES.values())
        .values_list("document_type", "content")
    )
    return {part: by_type.get(document_type, "") for part, document_type in PART_DOCUMENT_TYPES.items()}


def _line_price(act, line_prices):
    if act.id in line_prices:
        price = line_prices[act.id]
        return "" if act.prix_libre and not price else float(price)
    return "" if act.prix_libre else float(act.price)


@login_required
@role_required(*CLINICIAN_ROLES)
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
        if consultation.status == Consultation.Status.VALIDATED:
            # Lecture seule tant que le médecin n'a pas explicitement déverrouillé la consultation.
            messages.error(request, "Consultation validée : déverrouillez-la avant de la modifier.")
            return redirect("clinical:consultation_detail", appointment_id=appointment.pk)
        action = request.POST.get("action")
        missing_prices = _apply_consultation_post(request, consultation, cabinet)
        if action == "validate" and missing_prices:
            consultation.save()
            messages.error(request, f"Indiquez le prix de : {', '.join(missing_prices)}")
            return redirect("clinical:consultation_detail", appointment_id=appointment.pk)

        consultation.status = (
            Consultation.Status.VALIDATED if action == "validate" else Consultation.Status.DRAFT
        )
        consultation.save()

        if action == "validate":
            appointment.status = Appointment.Status.COMPLETED
            appointment.save(update_fields=["status"])
            if request.user.profile.sees_money:
                messages.success(
                    request,
                    f"Consultation validée et facture {consultation.invoice.invoice_number} transmise.",
                )
            else:
                messages.success(request, "Consultation validée et transmise à l'assistante pour l'encaissement.")
            return redirect("clinical:doctor_dashboard")

        messages.success(request, "Brouillon enregistré.")
        return redirect("clinical:consultation_detail", appointment_id=appointment.pk)

    all_acts = MedicalAct.objects.filter(cabinet=cabinet, is_active=True)
    line_prices = dict(consultation.consultation_acts.values_list("act_id", "price"))
    selected_act_ids = list(line_prices)
    sees_money = request.user.profile.sees_money
    acts_json = [
        {
            "id": act.id,
            "code": act.code,
            "name": act.name,
            # Remplaçant : aucun tarif dans la page (seul le montant d'un prix libre qu'il a saisi).
            "price": float(act.price) if sees_money else 0,
            # Prix déjà saisi sur la ligne de cette consultation (sinon tarif catalogue ;
            # vide pour un acte en prix libre tant que la doctoresse ne l'a pas saisi).
            "line_price": _line_price(act, line_prices) if sees_money or act.prix_libre else "",
            "is_quick_exam": act.is_quick_exam,
            "prix_libre": act.prix_libre,
        }
        for act in all_acts
    ]
    free_control = free_control_candidate(consultation)
    billing_json = {
        "discount": float(consultation.billing_discount or 0) if sees_money else 0,
        # Contrôle gratuit possible : case pré-cochée tant que la fiche n'a pas d'actes enregistrés.
        "free": consultation.billing_free or bool(
            free_control and consultation.status == Consultation.Status.DRAFT and not line_prices
        ),
    }
    part_contents = _prescription_contents(consultation)
    prescription_parts_json = [
        {"key": part, "label": info["label"], "field": info["field"], "content": part_contents[part]}
        for part, info in PRESCRIPTION_PARTS.items()
    ]
    modeles_ordonnance_json = [
        {"id": m.pk, "nom": m.nom, "medicaments": m.medicaments, "bilan": m.bilan_biologique,
         "radiologie": m.radiologie}
        for m in ModeleOrdonnance.objects.filter(cabinet=cabinet, actif=True)
    ]
    # Modèles de courrier déjà remplis pour cette patiente ({patiente}, {ddr}, {terme}…).
    valeurs = valeurs_champs(
        appointment.patient, consultation,
        doctor_name=doctor_display_name(consultation.doctor if consultation.doctor_id else request.user),
        ville=getattr(cabinet, "ville", ""),
    )
    courrier_types_json = [{"key": t["key"], "label": t["label"]} for t in COURRIER_TYPES]
    courrier_modeles_json = [
        {"id": m.pk, "type": m.type_document, "nom": m.nom, "texte": remplir(m.contenu, valeurs)}
        for m in ModeleCourrier.objects.filter(cabinet=cabinet, actif=True)
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
    # Historique complet : toutes les autres visites de la patiente, la plus récente d'abord.
    previous_consultations = enrich_visits(list(
        Consultation.objects.filter(cabinet=cabinet, patient=appointment.patient)
        .exclude(pk=consultation.pk)
        .select_related("appointment", "invoice")
        .prefetch_related("consultation_acts__act", "documents")
        .order_by("-appointment__date", "-pk")
    ))
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
            "billing_json": billing_json,
            "prescription_parts_json": prescription_parts_json,
            "modeles_ordonnance_json": modeles_ordonnance_json,
            "courrier_types_json": courrier_types_json,
            "courrier_types": COURRIER_TYPES,
            "courrier_modeles_json": courrier_modeles_json,
            "letters_json": letters_json,
            "patient_documents": patient_documents,
            "document_type_choices": PatientDocument.DocumentType.choices,
            "previous_consultations": previous_consultations,
            "free_control": free_control if sees_money else None,
            "sees_money": sees_money,
        },
    )


@login_required
@role_required(*CLINICIAN_ROLES)
@require_POST
def autosave_consultation(request, appointment_id):
    """Sauvegarde silencieuse (HTMX) de la fiche : ne change jamais le statut de la consultation."""
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation, _ = Consultation.objects.get_or_create(
        appointment=appointment,
        defaults={"patient": appointment.patient, "doctor": request.user, "cabinet": cabinet},
    )
    if consultation.status == Consultation.Status.VALIDATED:
        return HttpResponse("Consultation validée : lecture seule.", status=409)
    _apply_consultation_post(request, consultation, cabinet)
    # update_fields exclut `status` : une autosave en vol ne peut pas annuler une validation concurrente.
    consultation.save(
        update_fields=[
            "clinical_exam", "clinical_notes", "diagnostic", "gestational_age_weeks",
            "ultrasound_notes", "doctor", "billing_discount", "billing_free", "updated_at",
        ]
    )
    return HttpResponse(status=204)


LETTER_LABELS = {t["key"]: (t["key"], t["label"]) for t in COURRIER_TYPES}


def enrich_visits(consultations):
    """Prépare des consultations (avec appointment, actes et documents préchargés) pour
    l'affichage de l'historique : ordonnances, courriers, actes, terme et numéro de visite.

    Le numéro (« Consultation 1, 2, 3… ») suit l'ordre chronologique de TOUTES les
    consultations de la patiente, pas seulement celles affichées.
    """
    if not consultations:
        return consultations
    first = consultations[0]
    ordered_ids = list(
        Consultation.objects.filter(cabinet_id=first.cabinet_id, patient_id=first.patient_id)
        .order_by("appointment__date", "pk")
        .values_list("pk", flat=True)
    )
    numbers = {pk: index for index, pk in enumerate(ordered_ids, start=1)}
    for consultation in consultations:
        documents = {doc.document_type: doc for doc in consultation.documents.all()}
        prescription = documents.get(Document.DocumentType.PRESCRIPTION)
        consultation.prescription = prescription.content if prescription else ""
        # Bilan biologique et radiologie : affichés et imprimables seulement s'ils ont du contenu.
        consultation.extra_prescriptions = [
            (part, PRESCRIPTION_PARTS[part]["label"], documents[doc_type].content)
            for part, doc_type in PART_DOCUMENT_TYPES.items()
            if part != "medicaments" and doc_type in documents and documents[doc_type].content
        ]
        consultation.letters = [
            (key, label) for doc_type, (key, label) in LETTER_LABELS.items()
            if doc_type in documents and documents[doc_type].content
        ]
        # `acts` est le M2M du modèle : les lignes chargées vivent dans `act_lines`.
        consultation.act_lines = list(consultation.consultation_acts.all())
        consultation.quick_exams = [ca for ca in consultation.act_lines if ca.act.is_quick_exam]
        consultation.acts_total = sum((ca.price for ca in consultation.act_lines), 0)
        consultation.term = consultation.pregnancy
        consultation.number = numbers.get(consultation.pk)

    return consultations


@login_required
@role_required(*CLINICIAN_ROLES)
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
    enrich_visits(consultations)

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
            **documents_context(request, patient),
            # Remplaçant : aucune facture, ni dans la page ni dans son code source.
            "invoices": Invoice.objects.filter(cabinet=cabinet, patient=patient)
            .prefetch_related("payments").order_by("-created_at")
            if request.user.profile.sees_money else Invoice.objects.none(),
            "sees_money": request.user.profile.sees_money,
        },
    )


@login_required
@role_required(*CLINICIAN_ROLES)
@require_POST
def unlock_consultation(request, appointment_id):
    """Repasse une consultation validée en brouillon pour la modifier.

    La facture n'est pas touchée ici ; à la revalidation, Consultation._bill() ne réécrit
    jamais une facture déjà encaissée.
    """
    cabinet = request.user.profile.cabinet
    consultation = get_object_or_404(
        Consultation, appointment_id=appointment_id, appointment__cabinet=cabinet
    )
    if consultation.status == Consultation.Status.VALIDATED:
        consultation.status = Consultation.Status.DRAFT
        consultation.save(update_fields=["status", "updated_at"])
        messages.success(request, "Consultation déverrouillée : modifiez-la puis validez-la à nouveau.")
    return redirect("clinical:consultation_detail", appointment_id=appointment_id)


@login_required
@role_required(*CLINICIAN_ROLES)
def upload_patient_document(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    if request.method == "POST":
        consultation = Consultation.objects.filter(appointment=appointment, cabinet=cabinet).first()
        created, errors = save_documents(
            request.FILES.getlist("files") + request.FILES.getlist("file"),
            cabinet=cabinet,
            patient=appointment.patient,
            document_type=request.POST.get("document_type", ""),
            exam_date=parse_exam_date(request.POST.get("exam_date")) or timezone.localdate(),
            consultation=consultation,
            uploaded_by=request.user,
            title=request.POST.get("title", "").strip(),
        )
        for error in errors:
            messages.error(request, error)
        if created:
            messages.success(request, "Document ajouté au dossier de la patiente." if len(created) == 1
                             else f"{len(created)} documents ajoutés au dossier de la patiente.")
    return redirect("clinical:consultation_detail", appointment_id=appointment.pk)


@login_required
@role_required(*CLINICIAN_ROLES)
@xframe_options_sameorigin
def serve_patient_document(request, pk):
    """Ouvre un document joint (médecin uniquement, cabinet de l'utilisateur) — jamais via /media/ public."""
    document = get_object_or_404(PatientDocument, pk=pk, cabinet=request.user.profile.cabinet)
    try:
        handle = document.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("Fichier introuvable.")
    # HEIC : aucun navigateur ne l'affiche, on le propose au téléchargement.
    as_attachment = request.GET.get("download") == "1" or document.content_type == "image/heic"
    response = FileResponse(
        handle,
        as_attachment=as_attachment,
        filename=document.original_name or document.file.name.rsplit("/", 1)[-1],
        content_type=document.content_type or "application/octet-stream",
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@role_required(*CLINICIAN_ROLES)
def download_patient_record_pdf(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"), pk=appointment_id, cabinet=cabinet
    )
    pdf_bytes = generate_patient_record_pdf(appointment.patient, doctor=request.user)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="dossier_{appointment.patient.patient_number}.pdf"'
    )
    return response


@login_required
@role_required(*CLINICIAN_ROLES)
def download_full_patient_archive(request, patient_id):
    """ZIP contenant le PDF récapitulatif du dossier + tous les documents joints (radios/bilans)."""
    cabinet = request.user.profile.cabinet
    patient = get_object_or_404(Patient, pk=patient_id, cabinet=cabinet)

    pdf_bytes = generate_patient_record_pdf(patient, save_copy=False, doctor=request.user)
    documents = PatientDocument.objects.filter(cabinet=cabinet, patient=patient)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("patient_record.pdf", pdf_bytes)
        used_names = set()
        for doc in documents:
            if not doc.file:
                continue
            base_name = doc.original_name or doc.file.name.rsplit("/", 1)[-1]
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
@role_required(*CLINICIAN_ROLES)
def download_prescription_pdf(request, appointment_id, part="medicaments"):
    """Ordonnance d'une partie : médicaments (URL historique), bilan biologique ou radiologie."""
    if part not in PART_DOCUMENT_TYPES:
        raise Http404("Partie d'ordonnance inconnue.")
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation = get_object_or_404(Consultation, appointment=appointment, cabinet=cabinet)
    content = _prescription_contents(consultation)[part]
    pdf_bytes = generate_prescription_pdf(consultation, content, mode=mode_from_request(request), part=part)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = PRESCRIPTION_PARTS[part]["file"]
    response["Content-Disposition"] = f'inline; filename="{filename}_{consultation.patient.patient_number}.pdf"'
    return response


@login_required
@role_required(*CLINICIAN_ROLES)
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
    pdf_bytes = generate_letter_pdf(consultation, letter_type, content, mode=mode_from_request(request))
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{letter_type}_{consultation.patient.patient_number}.pdf"'
    )
    return response


@login_required
@role_required(*CLINICIAN_ROLES)
def download_report_pdf(request, appointment_id):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=appointment_id, cabinet=cabinet)
    consultation = get_object_or_404(Consultation, appointment=appointment, cabinet=cabinet)
    pdf_bytes = generate_report_pdf(consultation, mode=mode_from_request(request))
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="compte_rendu_{consultation.patient.patient_number}.pdf"'
    return response
