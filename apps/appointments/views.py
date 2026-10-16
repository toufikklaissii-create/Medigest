import calendar as calendar_module
import json
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile
from apps.billing.services import PAYMENT_SHORTCUTS, pending_invoices_queryset
from apps.clinical.models import Consultation
from apps.communications.views import _active_tasks_for
from apps.patients.models import Patient

from .intake import clean_intake_vitals
from .models import Appointment

NEXT_STATUS = {
    Appointment.Status.SCHEDULED: Appointment.Status.ARRIVED,
    Appointment.Status.ARRIVED: Appointment.Status.WAITING,
    Appointment.Status.WAITING: Appointment.Status.IN_CONSULTATION,
    Appointment.Status.IN_CONSULTATION: Appointment.Status.COMPLETED,
}

NEXT_STATUS_LABEL = {
    Appointment.Status.SCHEDULED: "Marquer arrivée",
    Appointment.Status.ARRIVED: "Mettre en attente",
    Appointment.Status.WAITING: "Démarrer consultation",
    Appointment.Status.IN_CONSULTATION: "Marquer terminée",
}

QUEUE_COLUMNS = [
    (Appointment.Status.ARRIVED, "Arrivée"),
    (Appointment.Status.WAITING, "En attente"),
    (Appointment.Status.IN_CONSULTATION, "En consultation"),
    (Appointment.Status.COMPLETED, "Terminée"),
]

DAY_START = time(8, 30)
DAY_END = time(18, 30)
SLOT_MINUTES = 30
DAY_START_MINUTES = DAY_START.hour * 60 + DAY_START.minute
DAY_END_MINUTES = DAY_END.hour * 60 + DAY_END.minute
DAY_TOTAL_MINUTES = DAY_END_MINUTES - DAY_START_MINUTES

REASON_PRESETS = [
    "Consultation de suivi",
    "Échographie",
    "Contrôle",
    "Première consultation",
    "Urgence",
]

STATUS_FILTERS = [
    ("all", "Tous"),
    (Appointment.Status.SCHEDULED, "Programmés"),
    (Appointment.Status.ARRIVED, "Arrivés"),
    (Appointment.Status.WAITING, "En attente"),
    (Appointment.Status.IN_CONSULTATION, "En consultation"),
    (Appointment.Status.COMPLETED, "Terminées"),
]


def _toast_header(message, toast_type="success"):
    return json.dumps({"toast": {"message": message, "type": toast_type}})


def _cabinet_doctor(cabinet):
    return User.objects.filter(
        profile__role=Profile.Role.DOCTOR, profile__cabinet=cabinet
    ).first()


# Patientes effectivement reçues : arrivées au cabinet (les RDV seulement planifiés ne comptent pas).
RECEIVED_STATUSES = (
    Appointment.Status.ARRIVED,
    Appointment.Status.WAITING,
    Appointment.Status.IN_CONSULTATION,
    Appointment.Status.COMPLETED,
)


def _today_appointments(cabinet):
    today = timezone.localdate()
    return (
        Appointment.objects.select_related("patient")
        .filter(cabinet=cabinet, date__date=today)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )


def _queue_board_context(cabinet):
    appointments = _today_appointments(cabinet)
    for appointment in appointments:
        appointment.next_label = NEXT_STATUS_LABEL.get(appointment.status)
    columns = []
    for status, label in QUEUE_COLUMNS:
        columns.append((status, label, [a for a in appointments if a.status == status]))
    return {"columns": columns}


# Action contextuelle de l'accueil : l'assistante ne fait avancer que l'arrivée et la mise en attente,
# le médecin prend le relais ensuite ; l'encaissement apparaît quand la facture est prête.
RECEPTION_ACTION_LABEL = {
    Appointment.Status.SCHEDULED: "Arrivée",
    Appointment.Status.ARRIVED: "Mettre en attente",
}


def _consultation_for(appointment):
    # Accès inverse OneToOne : RelatedObjectDoesNotExist hérite d'AttributeError.
    return getattr(appointment, "consultation", None)


def _invoice_for(appointment):
    consultation = _consultation_for(appointment)
    return consultation.invoice if consultation and consultation.invoice_id else None


def _timeline_context(cabinet):
    appointments = list(
        _today_appointments(cabinet).select_related("consultation__invoice")
    )
    for appointment in appointments:
        appointment.action_label = RECEPTION_ACTION_LABEL.get(appointment.status)
        appointment.invoice = _invoice_for(appointment)
    return {"timeline": appointments, **_day_counters(cabinet, appointments)}


def _day_counters(cabinet, appointments):
    # Aucun montant ici : les recettes du jour sont réservées à la doctoresse.
    S = Appointment.Status
    return {
        "count_total": len(appointments),
        "count_waiting": sum(1 for a in appointments if a.status in (S.ARRIVED, S.WAITING)),
        "count_in_consultation": sum(1 for a in appointments if a.status == S.IN_CONSULTATION),
    }


def _today_list_context(cabinet):
    appointments = _today_appointments(cabinet)
    scheduled_today = [a for a in appointments if a.status == Appointment.Status.SCHEDULED]
    return {"scheduled_today": scheduled_today}


def _reminder_day(cabinet, target_date):
    return (
        Appointment.objects.select_related("patient", "cabinet", "whatsapp_sent_by")
        .filter(cabinet=cabinet, date__date=target_date)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )


RELAUNCH_AFTER = timedelta(hours=24)


def _relaunch_appointments(cabinet):
    """RDV des 2 prochains jours : rappel sans réponse depuis plus de 24 h, ou numéro inutilisable."""
    now = timezone.now()
    candidates = (
        Appointment.objects.select_related("patient", "cabinet", "whatsapp_sent_by")
        .filter(
            cabinet=cabinet,
            status=Appointment.Status.SCHEDULED,
            date__gte=now,
            date__date__lte=timezone.localdate() + timedelta(days=2),
        )
        .exclude(whatsapp_status=Appointment.WhatsappStatus.CANCELLED)
        .order_by("date")
    )
    return [
        appt for appt in candidates
        if appt.whatsapp_phone_state != "ok"
        or (
            appt.whatsapp_status == Appointment.WhatsappStatus.SENT
            and appt.whatsapp_sent_at
            and appt.whatsapp_sent_at <= now - RELAUNCH_AFTER
        )
    ]


def _whatsapp_context(cabinet):
    today = timezone.localdate()
    j1_date, j2_date = today + timedelta(days=1), today + timedelta(days=2)
    j1 = list(_reminder_day(cabinet, j1_date))
    j2 = list(_reminder_day(cabinet, j2_date))
    relaunch = _relaunch_appointments(cabinet)
    return {
        "j1_appointments": j1,
        "j1_date": j1_date,
        "j2_appointments": j2,
        "j2_date": j2_date,
        "relaunch_appointments": relaunch,
        "whatsapp_total": len(j1) + len(j2) + len(relaunch),
    }


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _shift_month(anchor, delta):
    month_index = anchor.month - 1 + delta
    year = anchor.year + month_index // 12
    month = month_index % 12 + 1
    day = min(anchor.day, calendar_module.monthrange(year, month)[1])
    return date(year, month, day)


def _day_slots(start_minutes=DAY_START_MINUTES, end_minutes=DAY_END_MINUTES):
    slots = []
    minutes = start_minutes
    while minutes <= end_minutes:
        slots.append(time(minutes // 60, minutes % 60))
        minutes += SLOT_MINUTES
    return slots


def _day_context(cabinet, current_date, status_filter="all"):
    appointments = (
        Appointment.objects.select_related("patient")
        .filter(cabinet=cabinet, date__date=current_date)
        .order_by("date")
    )
    if status_filter and status_filter != "all":
        appointments = appointments.filter(status=status_filter)
    appointments = list(appointments)
    # Plage horaire de la grille : 08:30–18:30 par défaut, élargie à l'heure pleine pour
    # afficher les RDV tôt le matin ou en soirée (sinon ils s'empilaient en bas de grille).
    day_start, day_end = DAY_START_MINUTES, DAY_END_MINUTES
    for appt in appointments:
        local_dt = timezone.localtime(appt.date)
        begin = local_dt.hour * 60 + local_dt.minute
        finish = begin + (appt.duration_minutes or SLOT_MINUTES)
        if begin < day_start:
            day_start = (begin // 60) * 60
        if finish > day_end:
            day_end = min(-(-finish // 60) * 60, 24 * 60 - SLOT_MINUTES)
    day_total = day_end - day_start

    positioned = []
    for appt in appointments:
        local_dt = timezone.localtime(appt.date)
        start_minutes = local_dt.hour * 60 + local_dt.minute
        offset = start_minutes - day_start
        top_pct = min(max((offset / day_total) * 100, 0), 100)
        height_pct = max((appt.duration_minutes / day_total) * 100, 3.2)
        appt.top_pct = round(top_pct, 2)
        appt.height_pct = round(height_pct, 2)
        appt.next_label = NEXT_STATUS_LABEL.get(appt.status)
        appt.time_display = local_dt.strftime("%H:%M")
        appt.date_iso = local_dt.strftime("%Y-%m-%dT%H:%M")
        positioned.append(appt)

    now_pct = None
    if current_date == timezone.localdate():
        now_local = timezone.localtime(timezone.now())
        now_minutes = now_local.hour * 60 + now_local.minute
        if day_start <= now_minutes <= day_end:
            now_pct = round(((now_minutes - day_start) / day_total) * 100, 2)

    return {
        "slots": _day_slots(day_start, day_end),
        # Hauteur exacte de la grille (1 ligne de 48 px par créneau) : les cartes sont
        # positionnées en % de cette hauteur, elle ne doit pas s'étirer avec la page.
        "grid_height": (day_end - day_start) // SLOT_MINUTES * 48,
        "day_appointments": positioned,
        "now_pct": now_pct,
    }


def _month_context(cabinet, current_date):
    cal = calendar_module.Calendar(firstweekday=0)
    weeks = list(cal.monthdatescalendar(current_date.year, current_date.month))

    month_appointments = (
        Appointment.objects.select_related("patient")
        .filter(cabinet=cabinet, date__date__gte=weeks[0][0], date__date__lte=weeks[-1][-1])
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )
    by_day = {}
    for appt in month_appointments:
        by_day.setdefault(timezone.localtime(appt.date).date(), []).append(appt)

    today = timezone.localdate()
    grid = []
    for week in weeks:
        row = []
        for day in week:
            day_appts = by_day.get(day, [])
            count = len(day_appts)
            if count == 0:
                load = "none"
            elif count <= 4:
                load = "normal"
            elif count <= 8:
                load = "busy"
            else:
                load = "full"
            row.append(
                {
                    "date": day,
                    "in_month": day.month == current_date.month,
                    "is_today": day == today,
                    "appointments": day_appts[:3],
                    "extra_count": max(count - 3, 0),
                    "total": count,
                    "load": load,
                }
            )
        grid.append(row)

    return {"month_grid": grid}


def _calendar_extra_context(cabinet, current_date):
    return {
        "today": timezone.localdate(),
        "prev_date": current_date - timedelta(days=1),
        "next_date": current_date + timedelta(days=1),
        "prev_month": _shift_month(current_date, -1),
        "next_month": _shift_month(current_date, 1),
        "reason_presets": REASON_PRESETS,
        "status_filters": STATUS_FILTERS,
        **_month_context(cabinet, current_date),
    }


@login_required
def appointment_calendar(request):
    view_mode = request.GET.get("view", "day")
    if view_mode not in ("day", "month"):
        view_mode = "day"
    current_date = _parse_date(request.GET.get("date")) or timezone.localdate()
    status_filter = request.GET.get("status", "all")

    cabinet = request.user.profile.cabinet
    context = {
        "view_mode": view_mode,
        "current_date": current_date,
        "status_filter": status_filter,
        **_calendar_extra_context(cabinet, current_date),
    }
    if view_mode == "day":
        context.update(_day_context(cabinet, current_date, status_filter))

    if request.headers.get("HX-Request"):
        response = render(request, "assistant/_calendar_container.html", context)
        response.headers["HX-Push-Url"] = (
            f"{request.path}?view={view_mode}&date={current_date.isoformat()}&status={status_filter}"
        )
        return response
    return render(request, "assistant/calendar.html", context)


def _render_day_fragment(request, anchor_date, toast_message=None):
    cabinet = request.user.profile.cabinet
    context = {
        "view_mode": "day",
        "current_date": anchor_date,
        "status_filter": "all",
        **_calendar_extra_context(cabinet, anchor_date),
        **_day_context(cabinet, anchor_date),
    }
    response = render(request, "assistant/_calendar_body.html", context)
    events = {"refreshCalendar": True}
    if toast_message:
        events["toast"] = {"message": toast_message, "type": "success"}
    response.headers["HX-Trigger"] = json.dumps(events)
    response.headers["HX-Push-Url"] = (
        f"{reverse('appointments:calendar')}?view=day&date={anchor_date.isoformat()}"
    )
    return response


@login_required
def appointment_modal(request):
    """GET: renders the pre-filled 'create appointment' modal content for a given slot."""
    prefill_date = _parse_date(request.GET.get("date")) or timezone.localdate()
    prefill_time = request.GET.get("time", "")
    return render(
        request,
        "assistant/_appointment_modal_content.html",
        {
            "prefill_date": prefill_date,
            "prefill_time": prefill_time,
            "reason_presets": REASON_PRESETS,
        },
    )


@login_required
def appointment_drawer(request, pk):
    """GET: renders the appointment detail drawer content."""
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"),
        pk=pk,
        cabinet=request.user.profile.cabinet,
    )
    consultation = Consultation.objects.filter(appointment=appointment).first()
    return render(
        request,
        "assistant/_appointment_drawer_content.html",
        {
            "appointment": appointment,
            "next_label": NEXT_STATUS_LABEL.get(appointment.status),
            "consultation": consultation,
            "from_whatsapp": request.GET.get("from") == "whatsapp",
        },
    )


@login_required
def intake_vitals_modal(request, pk):
    """GET: renders the standalone 'Constantes d'accueil' modal for the kanban entry point."""
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient"),
        pk=pk,
        cabinet=request.user.profile.cabinet,
    )
    consultation = Consultation.objects.filter(appointment=appointment).first()
    return render(
        request,
        "assistant/_intake_vitals_modal.html",
        {"appointment": appointment, "consultation": consultation},
    )


@login_required
def save_intake_vitals(request, pk):
    """POST: saves Tension/Poids/Taille/DDR onto the appointment's Consultation,
    plus the patient's antécédents (Patient.medical_history).

    Only ever touches these intake fields — never clinical_exam, clinical_notes,
    diagnostic, or ultrasound_notes — so this endpoint stays safe to expose
    to the assistant role regardless of caller. Invalid input re-renders the
    form with a message under each field (never a 500).
    """
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment.objects.select_related("patient"), pk=pk, cabinet=cabinet)
    consultation = Consultation.objects.filter(appointment=appointment).first()
    error_message = None
    errors = {}
    values = None

    if request.method == "POST":
        cleaned, errors, values = clean_intake_vitals(request.POST, timezone.localdate())
        if errors:
            error_message = "Certaines constantes sont invalides : corrigez les champs signalés."
        elif consultation is None:
            doctor = _cabinet_doctor(cabinet)
            if doctor is None:
                error_message = (
                    "Aucun médecin n'est rattaché à ce cabinet : "
                    "impossible d'enregistrer les constantes."
                )
            else:
                consultation = Consultation.objects.create(
                    appointment=appointment,
                    patient=appointment.patient,
                    cabinet=cabinet,
                    doctor=doctor,
                )

        if not errors and consultation is not None:
            consultation.blood_pressure = cleaned["blood_pressure"]
            consultation.weight_kg = cleaned["weight_kg"]
            consultation.height_cm = cleaned["height_cm"]
            consultation.last_menstrual_period = cleaned["last_menstrual_period"]
            consultation.save(
                update_fields=[
                    "blood_pressure",
                    "weight_kg",
                    "height_cm",
                    "last_menstrual_period",
                ]
            )
            if "medical_history" in request.POST:
                appointment.patient.medical_history = cleaned["medical_history"]
                appointment.patient.save(update_fields=["medical_history"])
            values = None

    response = render(
        request,
        "assistant/_intake_vitals_form.html",
        {"appointment": appointment, "consultation": consultation, "errors": errors, "values": values},
    )
    if error_message:
        response.headers["HX-Trigger"] = _toast_header(error_message, "error")
    elif consultation is not None and request.method == "POST":
        response.headers["HX-Trigger"] = _toast_header(
            f"{appointment.patient.full_name} — constantes enregistrées."
        )
    return response


@login_required
def create_appointment_ajax(request):
    """POST: creates a RDV from patiente_id/date/heure/motif and refreshes the day grid."""
    if request.method != "POST":
        return redirect("appointments:calendar")

    anchor_date = timezone.localdate()
    patient_id = request.POST.get("patient")
    date_str = request.POST.get("date")
    time_str = request.POST.get("time")
    toast_message = None

    if patient_id and date_str and time_str:
        patient = get_object_or_404(
            Patient, pk=patient_id, cabinet=request.user.profile.cabinet
        )
        naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        parsed_date = timezone.make_aware(naive_dt)
        Appointment.objects.create(
            cabinet=request.user.profile.cabinet,
            patient=patient,
            date=parsed_date,
            duration_minutes=request.POST.get("duration_minutes") or 30,
            reason=request.POST.get("reason", "").strip(),
            admin_notes=request.POST.get("admin_notes", "").strip(),
        )
        anchor_date = parsed_date.date()
        toast_message = f"RDV créé pour {patient.full_name}."

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def update_appointment_ajax(request, pk):
    """POST: reschedules a RDV to a new date/heure and refreshes the day grid."""
    appointment = get_object_or_404(
        Appointment, pk=pk, cabinet=request.user.profile.cabinet
    )
    anchor_date = timezone.localtime(appointment.date).date()
    toast_message = None

    if request.method == "POST":
        date_str = request.POST.get("date")
        time_str = request.POST.get("time")
        if date_str and time_str:
            naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            parsed_date = timezone.make_aware(naive_dt)
            appointment.date = parsed_date
            appointment.save(update_fields=["date"])
            anchor_date = parsed_date.date()
            toast_message = (
                f"{appointment.patient.full_name} — RDV reprogrammé au {anchor_date:%d/%m/%Y} à {time_str}."
            )

    if request.POST.get("source") == "whatsapp":
        # Depuis « À déplacer » (accueil) : le tiroir reste ouvert et propose d'envoyer le
        # nouveau créneau ; la liste des rappels est rafraîchie en hx-swap-oob.
        response = render(
            request,
            "assistant/_drawer_reschedule.html",
            {
                "appointment": appointment,
                "from_whatsapp": True,
                "rescheduled": toast_message is not None,
                "oob_reminders": True,
                **_whatsapp_context(request.user.profile.cabinet),
            },
        )
        if toast_message:
            response.headers["HX-Trigger"] = _toast_header(toast_message)
        return response

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def cancel_appointment_ajax(request, pk):
    """POST: sets a RDV status to 'Cancelled' and refreshes the day grid."""
    appointment = get_object_or_404(
        Appointment, pk=pk, cabinet=request.user.profile.cabinet
    )
    toast_message = None
    anchor_date = timezone.localtime(appointment.date).date()

    if request.method == "POST":
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=["status"])
        toast_message = f"{appointment.patient.full_name} — RDV annulé."

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def calendar_advance_status(request, pk):
    appointment = get_object_or_404(
        Appointment, pk=pk, cabinet=request.user.profile.cabinet
    )
    toast_message = None
    anchor_date = timezone.localtime(appointment.date).date()

    if request.method == "POST":
        next_status = NEXT_STATUS.get(appointment.status)
        if next_status:
            appointment.status = next_status
            appointment.save(update_fields=["status"])
            toast_message = f"{appointment.patient.full_name} — statut mis à jour."

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def patient_picker_search(request):
    query = request.GET.get("q", "").strip()
    patients = []
    if query:
        patients = Patient.objects.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(cin__icontains=query)
            | Q(patient_number__icontains=query),
            cabinet=request.user.profile.cabinet,
        )[:8]
    return render(
        request, "assistant/_patient_picker_results.html", {"patients": patients, "query": query}
    )


@login_required
def select_patient_for_slot(request, pk):
    patient = get_object_or_404(Patient, pk=pk, cabinet=request.user.profile.cabinet)
    return render(request, "assistant/_patient_picker.html", {"selected_patient": patient})


@login_required
def quick_create_patient(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if first_name and last_name:
            patient = Patient.objects.create(
                cabinet=request.user.profile.cabinet,
                first_name=first_name,
                last_name=last_name,
                phone=request.POST.get("phone", "").strip(),
            )
            return render(
                request, "assistant/_patient_picker.html", {"selected_patient": patient}
            )
    return render(request, "assistant/_patient_picker.html", {"express_error": True})


@login_required
def assistant_dashboard(request):
    cabinet = request.user.profile.cabinet
    pending_invoices = list(pending_invoices_queryset(cabinet))
    my_tasks = _active_tasks_for(request.user)
    context = {
        **_timeline_context(cabinet),
        **_whatsapp_context(cabinet),
        "pending_invoices": pending_invoices,
        "pending_invoices_total": sum(invoice.balance_due for invoice in pending_invoices),
        "my_tasks": my_tasks,
        "urgent_tasks_count": sum(1 for t in my_tasks if t.priority == "urgent"),
        "today_total": _today_appointments(cabinet).filter(status__in=RECEIVED_STATUSES).count(),
    }
    return render(request, "assistant/dashboard.html", context)


@login_required
def create_appointment(request, patient_id=None):
    cabinet = request.user.profile.cabinet
    patient = (
        get_object_or_404(Patient, pk=patient_id, cabinet=cabinet) if patient_id else None
    )
    if request.method == "POST":
        patient_pk = patient_id or request.POST.get("patient")
        patient = get_object_or_404(Patient, pk=patient_pk, cabinet=cabinet)
        date = request.POST.get("date")
        if date:
            parsed_date = datetime.fromisoformat(date)
            if timezone.is_naive(parsed_date):
                parsed_date = timezone.make_aware(parsed_date)
            Appointment.objects.create(
                cabinet=cabinet,
                patient=patient,
                date=parsed_date,
                duration_minutes=request.POST.get("duration_minutes") or 30,
                reason=request.POST.get("reason", "").strip(),
            )
            messages.success(request, f"RDV créé pour {patient.full_name}.")
            return redirect("appointments:assistant_dashboard")
        messages.error(request, "La date du RDV est obligatoire.")

    patients = Patient.objects.filter(cabinet=cabinet)[:100] if not patient else None
    return render(
        request, "appointments/create.html", {"patient": patient, "patients": patients}
    )


@login_required
def patient_search(request):
    query = request.GET.get("q", "").strip()
    patients = []
    if query:
        patients = Patient.objects.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(phone__icontains=query)
            | Q(cin__icontains=query)
            | Q(patient_number__icontains=query),
            cabinet=request.user.profile.cabinet,
        )[:15]
    return render(request, "assistant/_search_results.html", {"patients": patients, "query": query})


@login_required
def advance_status(request, pk):
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment, pk=pk, cabinet=cabinet)
    toast_message = None
    if request.method == "POST":
        next_status = NEXT_STATUS.get(appointment.status)
        if next_status:
            appointment.status = next_status
            appointment.save(update_fields=["status"])
            toast_message = f"{appointment.patient.full_name} — statut mis à jour."

    if request.headers.get("HX-Target") == "timeline":
        response = render(request, "assistant/_timeline.html", _timeline_context(cabinet))
        if toast_message:
            response.headers["HX-Trigger"] = json.dumps(
                {"toast": {"message": toast_message, "type": "success"}, "panel-refresh": True}
            )
        return response

    response = render(request, "assistant/_queue_board.html", _queue_board_context(cabinet))
    if toast_message:
        response.headers["HX-Trigger"] = _toast_header(toast_message)
    return response


@login_required
def reception_timeline(request):
    """GET (HTMX, toutes les 15 s) : timeline du jour + compteurs en hx-swap-oob."""
    return render(request, "assistant/_timeline.html", _timeline_context(request.user.profile.cabinet))


@login_required
def reception_panel(request, pk):
    """GET (HTMX) : panneau d'accueil de la patiente sélectionnée.

    Uniquement des données administratives : constantes d'accueil, rappel WhatsApp,
    encaissement. Aucune donnée clinique (diagnostic, observations, ordonnances).
    """
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(
        Appointment.objects.select_related("patient", "consultation__invoice"), pk=pk, cabinet=cabinet
    )
    consultation = _consultation_for(appointment)
    return render(
        request,
        "assistant/_reception_panel.html",
        {
            "appointment": appointment,
            "consultation": consultation,
            "invoice": _invoice_for(appointment),
            "action_label": RECEPTION_ACTION_LABEL.get(appointment.status),
            "payment_shortcuts": PAYMENT_SHORTCUTS,
        },
    )


WHATSAPP_ACTIONS = {
    "send": (Appointment.WhatsappStatus.SENT, "Rappel WhatsApp envoyé à {patient}."),
    "relaunch": (Appointment.WhatsappStatus.SENT, "Relance WhatsApp envoyée à {patient}."),
    "send_rescheduled": (Appointment.WhatsappStatus.SENT, "Nouveau créneau envoyé à {patient}."),
    "confirm": (Appointment.WhatsappStatus.CONFIRMED, "{patient} a confirmé son RDV."),
    "reschedule": (Appointment.WhatsappStatus.RESCHEDULED, "{patient} souhaite déplacer son RDV."),
    "cancel": (Appointment.WhatsappStatus.CANCELLED, "RDV de {name} annulé, créneau libéré."),
}


@login_required
def whatsapp_action(request, pk, action):
    """POST (HTMX) : trace un envoi wa.me (ouvert côté navigateur) ou la réponse de la patiente.

    « cancel » annule aussi le RDV (créneau libéré) ; « reschedule » ouvre le tiroir du RDV
    sur le champ date/heure. Accessible à l'assistante comme à la doctoresse, toujours limité
    au cabinet de l'utilisateur.
    """
    cabinet = request.user.profile.cabinet
    appointment = get_object_or_404(Appointment.objects.select_related("patient"), pk=pk, cabinet=cabinet)
    events = {}
    if request.method == "POST" and action in WHATSAPP_ACTIONS:
        new_status, message_template = WHATSAPP_ACTIONS[action]
        if new_status == Appointment.WhatsappStatus.SENT:
            appointment.mark_whatsapp_sent(request.user)
        else:
            appointment.whatsapp_status = new_status
            update_fields = ["whatsapp_status"]
            if action == "cancel":
                appointment.status = Appointment.Status.CANCELLED
                update_fields.append("status")
            appointment.save(update_fields=update_fields)
        if action == "reschedule":
            events["whatsapp-reschedule"] = {
                "url": f"{reverse('appointments:appointment_drawer', args=[pk])}?from=whatsapp"
            }
        patient = appointment.patient
        message = message_template.format(patient=patient.full_name, name=patient.full_name)
        events["toast"] = {"message": message, "type": "success"}
        events["panel-refresh"] = True

    response = render(request, "assistant/_j2_reminders.html", _whatsapp_context(cabinet))
    if events:
        response.headers["HX-Trigger"] = json.dumps(events)
    return response
