import calendar as calendar_module
import json
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice
from apps.communications.views import _active_tasks_for
from apps.patients.models import Patient

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


def _today_appointments():
    today = timezone.localdate()
    return (
        Appointment.objects.select_related("patient")
        .filter(date__date=today)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )


def _queue_board_context():
    appointments = _today_appointments()
    for appointment in appointments:
        appointment.next_label = NEXT_STATUS_LABEL.get(appointment.status)
    columns = []
    for status, label in QUEUE_COLUMNS:
        columns.append((status, label, [a for a in appointments if a.status == status]))
    return {"columns": columns}


def _today_list_context():
    appointments = _today_appointments()
    scheduled_today = [a for a in appointments if a.status == Appointment.Status.SCHEDULED]
    return {"scheduled_today": scheduled_today}


def _j2_context():
    target_date = timezone.localdate() + timezone.timedelta(days=2)
    appointments = (
        Appointment.objects.select_related("patient")
        .filter(date__date=target_date)
        .exclude(status=Appointment.Status.CANCELLED)
        .order_by("date")
    )
    return {"j2_appointments": appointments, "j2_date": target_date}


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


def _day_slots():
    slots = []
    minutes = DAY_START_MINUTES
    while minutes <= DAY_END_MINUTES:
        slots.append(time(minutes // 60, minutes % 60))
        minutes += SLOT_MINUTES
    return slots


def _day_context(current_date, status_filter="all"):
    appointments = (
        Appointment.objects.select_related("patient")
        .filter(date__date=current_date)
        .order_by("date")
    )
    if status_filter and status_filter != "all":
        appointments = appointments.filter(status=status_filter)
    positioned = []
    for appt in appointments:
        local_dt = timezone.localtime(appt.date)
        start_minutes = local_dt.hour * 60 + local_dt.minute
        offset = start_minutes - DAY_START_MINUTES
        top_pct = min(max((offset / DAY_TOTAL_MINUTES) * 100, 0), 100)
        height_pct = max((appt.duration_minutes / DAY_TOTAL_MINUTES) * 100, 3.2)
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
        if DAY_START_MINUTES <= now_minutes <= DAY_END_MINUTES:
            now_pct = round(((now_minutes - DAY_START_MINUTES) / DAY_TOTAL_MINUTES) * 100, 2)

    return {
        "slots": _day_slots(),
        "day_appointments": positioned,
        "now_pct": now_pct,
    }


def _month_context(current_date):
    cal = calendar_module.Calendar(firstweekday=0)
    weeks = list(cal.monthdatescalendar(current_date.year, current_date.month))

    month_appointments = (
        Appointment.objects.select_related("patient")
        .filter(date__date__gte=weeks[0][0], date__date__lte=weeks[-1][-1])
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


def _calendar_extra_context(current_date):
    return {
        "today": timezone.localdate(),
        "prev_date": current_date - timedelta(days=1),
        "next_date": current_date + timedelta(days=1),
        "prev_month": _shift_month(current_date, -1),
        "next_month": _shift_month(current_date, 1),
        "reason_presets": REASON_PRESETS,
        "status_filters": STATUS_FILTERS,
        **_month_context(current_date),
    }


@login_required
def appointment_calendar(request):
    view_mode = request.GET.get("view", "day")
    if view_mode not in ("day", "month"):
        view_mode = "day"
    current_date = _parse_date(request.GET.get("date")) or timezone.localdate()
    status_filter = request.GET.get("status", "all")

    context = {
        "view_mode": view_mode,
        "current_date": current_date,
        "status_filter": status_filter,
        **_calendar_extra_context(current_date),
    }
    if view_mode == "day":
        context.update(_day_context(current_date, status_filter))

    if request.headers.get("HX-Request"):
        response = render(request, "assistant/_calendar_body.html", context)
        response.headers["HX-Push-Url"] = (
            f"{request.path}?view={view_mode}&date={current_date.isoformat()}&status={status_filter}"
        )
        return response
    return render(request, "assistant/calendar.html", context)


def _render_day_fragment(request, anchor_date, toast_message=None):
    context = {
        "view_mode": "day",
        "current_date": anchor_date,
        "status_filter": "all",
        **_calendar_extra_context(anchor_date),
        **_day_context(anchor_date),
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
    appointment = get_object_or_404(Appointment.objects.select_related("patient"), pk=pk)
    return render(
        request,
        "assistant/_appointment_drawer_content.html",
        {
            "appointment": appointment,
            "next_label": NEXT_STATUS_LABEL.get(appointment.status),
        },
    )


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
        patient = get_object_or_404(Patient, pk=patient_id)
        naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        parsed_date = timezone.make_aware(naive_dt)
        Appointment.objects.create(
            patient=patient,
            date=parsed_date,
            duration_minutes=request.POST.get("duration_minutes") or 30,
            reason=request.POST.get("reason", "").strip(),
            admin_notes=request.POST.get("admin_notes", "").strip(),
        )
        anchor_date = parsed_date.date()
        toast_message = f"RDV créé pour {patient}."

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def update_appointment_ajax(request, pk):
    """POST: reschedules a RDV to a new date/heure and refreshes the day grid."""
    appointment = get_object_or_404(Appointment, pk=pk)
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
                f"{appointment.patient} — RDV reprogrammé au {anchor_date:%d/%m/%Y} à {time_str}."
            )

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def cancel_appointment_ajax(request, pk):
    """POST: sets a RDV status to 'Cancelled' and refreshes the day grid."""
    appointment = get_object_or_404(Appointment, pk=pk)
    toast_message = None
    anchor_date = timezone.localtime(appointment.date).date()

    if request.method == "POST":
        appointment.status = Appointment.Status.CANCELLED
        appointment.save(update_fields=["status"])
        toast_message = f"{appointment.patient} — RDV annulé."

    return _render_day_fragment(request, anchor_date, toast_message)


@login_required
def calendar_advance_status(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    toast_message = None
    anchor_date = timezone.localtime(appointment.date).date()

    if request.method == "POST":
        next_status = NEXT_STATUS.get(appointment.status)
        if next_status:
            appointment.status = next_status
            appointment.save(update_fields=["status"])
            toast_message = f"{appointment.patient} — statut mis à jour."

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
            | Q(patient_number__icontains=query)
        )[:8]
    return render(
        request, "assistant/_patient_picker_results.html", {"patients": patients, "query": query}
    )


@login_required
def select_patient_for_slot(request, pk):
    patient = get_object_or_404(Patient, pk=pk)
    return render(request, "assistant/_patient_picker.html", {"selected_patient": patient})


@login_required
def quick_create_patient(request):
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if first_name and last_name:
            patient = Patient.objects.create(
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
    context = {
        **_queue_board_context(),
        **_today_list_context(),
        **_j2_context(),
        "pending_invoices": Invoice.objects.select_related("patient").filter(
            status=Invoice.Status.PENDING
        ),
        "my_tasks": _active_tasks_for(request.user),
        "today_total": _today_appointments().count(),
    }
    return render(request, "assistant/dashboard.html", context)


@login_required
def create_appointment(request, patient_id=None):
    patient = get_object_or_404(Patient, pk=patient_id) if patient_id else None
    if request.method == "POST":
        patient_pk = patient_id or request.POST.get("patient")
        patient = get_object_or_404(Patient, pk=patient_pk)
        date = request.POST.get("date")
        if date:
            parsed_date = datetime.fromisoformat(date)
            if timezone.is_naive(parsed_date):
                parsed_date = timezone.make_aware(parsed_date)
            Appointment.objects.create(
                patient=patient,
                date=parsed_date,
                duration_minutes=request.POST.get("duration_minutes") or 30,
                reason=request.POST.get("reason", "").strip(),
            )
            messages.success(request, f"RDV créé pour {patient}.")
            return redirect("appointments:assistant_dashboard")
        messages.error(request, "La date du RDV est obligatoire.")

    patients = Patient.objects.all()[:100] if not patient else None
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
            | Q(patient_number__icontains=query)
        )[:15]
    return render(request, "assistant/_search_results.html", {"patients": patients, "query": query})


@login_required
def advance_status(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk)
    toast_message = None
    if request.method == "POST":
        next_status = NEXT_STATUS.get(appointment.status)
        if next_status:
            appointment.status = next_status
            appointment.save(update_fields=["status"])
            toast_message = f"{appointment.patient} — statut mis à jour."

    response = render(request, "assistant/_queue_board.html", _queue_board_context())
    if toast_message:
        response.headers["HX-Trigger"] = _toast_header(toast_message)
    return response


WHATSAPP_ACTIONS = {
    "send": (Appointment.WhatsappStatus.SENT, "Rappel WhatsApp J-2 envoyé (simulation) à {patient}."),
    "confirm": (Appointment.WhatsappStatus.CONFIRMED, "{patient} a confirmé son RDV (simulation)."),
    "reschedule": (Appointment.WhatsappStatus.RESCHEDULED, "{patient} souhaite déplacer son RDV (simulation)."),
    "cancel": (Appointment.WhatsappStatus.CANCELLED, "{patient} a annulé son RDV (simulation)."),
}


@login_required
def whatsapp_action(request, pk, action):
    appointment = get_object_or_404(Appointment, pk=pk)
    toast_message = None
    if request.method == "POST" and action in WHATSAPP_ACTIONS:
        new_status, message_template = WHATSAPP_ACTIONS[action]
        appointment.whatsapp_status = new_status
        appointment.save(update_fields=["whatsapp_status"])
        toast_message = message_template.format(patient=appointment.patient)

    response = render(request, "assistant/_j2_reminders.html", _j2_context())
    if toast_message:
        response.headers["HX-Trigger"] = _toast_header(toast_message)
    return response
