"""Caisse : clôture à l'aveugle (assistante) ; Recettes du jour, rapports et exports (doctoresse).

L'assistante ne voit jamais un total, un montant attendu ni un écart : tout ce qui agrège les
recettes est réservé à la doctoresse, côté serveur.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.common.templatetags.medigest_format import dh

from .exports import build_revenue_pdf, build_revenue_xlsx, export_filename
from .models import CashClosing
from .reports import (
    PERIOD_CHOICES,
    cash_journal,
    close_cash_day,
    format_long_date,
    local_today,
    parse_iso_date,
    period_from_params,
    revenue_report,
)
from .services import BillingError, parse_amount
from .views import _hx_trigger, _toast


def _cabinet(request):
    return request.user.profile.cabinet


# ── Caisse ───────────────────────────────────────────────────────────────────

def _journal_context(request, day, **extra):
    """Journal complet (doctoresse) : encaissements, totaux, attendu, écart, historique."""
    context = cash_journal(_cabinet(request), day)
    context.update(
        _day_navigation(day),
        can_close=day <= local_today() and context["closing"] is None,
        show_history=True,
        closings=CashClosing.objects.filter(cabinet=_cabinet(request)).select_related("closed_by")[:30],
        **extra,
    )
    return context


def _requested_day(value):
    return min(parse_iso_date(value, local_today()), local_today())


def _day_navigation(day):
    today = local_today()
    return {
        "day": day,
        "day_label": format_long_date(day),
        "is_today": day == today,
        "previous_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1) if day < today else None,
        "today": today,
    }


def _blind_context(request, day, **extra):
    """Clôture à l'aveugle : ni attendu, ni total, ni écart — seulement l'état de la journée."""
    closing = CashClosing.objects.filter(cabinet=_cabinet(request), date=day).select_related("closed_by").first()
    return {
        **_day_navigation(day),
        "closing": closing,
        "can_close": day <= local_today() and closing is None,
        **extra,
    }


@login_required
@role_required("doctor", "assistant")
def cash_register(request):
    """Caisse de l'assistante (clôture à l'aveugle) ; la doctoresse est renvoyée vers ses recettes."""
    if request.user.profile.is_doctor:
        url = reverse("billing:daily_revenue")
        return redirect(f"{url}?date={request.GET['date']}" if request.GET.get("date") else url)
    context = _blind_context(request, _requested_day(request.GET.get("date")))
    if request.headers.get("HX-Request"):
        return render(request, "billing/_blind_closing.html", context)
    return render(request, "billing/cash_close_blind.html", context)


@login_required
@role_required("doctor")
def daily_revenue(request):
    """Recettes du jour : journal des encaissements, totaux, clôture et écart."""
    context = _journal_context(request, _requested_day(request.GET.get("date")))
    if request.headers.get("HX-Request"):
        return render(request, "billing/_cash_journal.html", context)
    return render(request, "billing/cash_register.html", context)


@login_required
@role_required("doctor", "assistant")
@require_POST
def cash_close(request):
    day = parse_iso_date(request.POST.get("date"), local_today())
    raw = request.POST.get("counted_cash", "")
    note = request.POST.get("note", "")
    counted = parse_amount(raw)
    blind = not request.user.profile.is_doctor
    try:
        closing = close_cash_day(_cabinet(request), day, counted, note, request.user)
    except BillingError as error:
        if blind:
            context = _blind_context(request, day, close_error=str(error), counted_input=raw, note_input=note)
            return render(request, "billing/_blind_closing.html", context)
        context = _journal_context(request, day, close_error=str(error), counted_input=raw, note_input=note)
        return render(request, "billing/_cash_journal.html", context)
    if blind:
        response = render(request, "billing/_blind_closing.html", _blind_context(request, day, just_closed=True))
        return _hx_trigger(response, toast=_toast("Clôture enregistrée."))
    if closing.difference:
        message = f"Caisse clôturée · écart de {dh(closing.difference)}."
    else:
        message = "Caisse clôturée · aucun écart."
    response = render(request, "billing/_cash_journal.html", _journal_context(request, day))
    return _hx_trigger(response, toast=_toast(message, "error" if closing.difference else "success"))


# ── Rapports & exports (doctoresse) ──────────────────────────────────────────

@login_required
@role_required("doctor")
def reports(request):
    period = period_from_params(request.GET)
    context = {
        **revenue_report(_cabinet(request), period),
        "period_choices": PERIOD_CHOICES,
        "previous_query": period.shifted(-1).query(),
        "next_query": period.shifted(1).query() if period.end < local_today() else None,
    }
    if request.headers.get("HX-Request"):
        return render(request, "billing/_report_body.html", {**context, "sync_date": bool(request.GET.get("nav"))})
    return render(request, "billing/reports.html", context)


@login_required
@role_required("doctor")
def export_xlsx(request):
    period = period_from_params(request.GET)
    cabinet = _cabinet(request)
    content = build_revenue_xlsx(cabinet, revenue_report(cabinet, period))
    response = HttpResponse(
        content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{export_filename(cabinet, period, "xlsx")}"'
    return response


@login_required
@role_required("doctor")
def export_pdf(request):
    period = period_from_params(request.GET)
    cabinet = _cabinet(request)
    content = build_revenue_pdf(cabinet, revenue_report(cabinet, period), request.user)
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{export_filename(cabinet, period, "pdf")}"'
    return response
