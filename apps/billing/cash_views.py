"""Caisse (journal + clôture, deux rôles) et Rapports / exports (doctoresse uniquement)."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
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
    today = local_today()
    context = cash_journal(_cabinet(request), day)
    context.update(
        day_label=format_long_date(day),
        is_today=day == today,
        previous_day=day - timedelta(days=1),
        next_day=day + timedelta(days=1) if day < today else None,
        today=today,
        can_close=day <= today and context["closing"] is None,
        **extra,
    )
    if request.user.profile.is_doctor:
        context["show_history"] = True
        context["closings"] = (
            CashClosing.objects.filter(cabinet=_cabinet(request)).select_related("closed_by")[:30]
        )
    return context


@login_required
@role_required("doctor", "assistant")
def cash_register(request):
    day = min(parse_iso_date(request.GET.get("date"), local_today()), local_today())
    context = _journal_context(request, day)
    if request.headers.get("HX-Request"):
        return render(request, "billing/_cash_journal.html", context)
    return render(request, "billing/cash_register.html", context)


@login_required
@role_required("doctor", "assistant")
@require_POST
def cash_close(request):
    day = parse_iso_date(request.POST.get("date"), local_today())
    raw = request.POST.get("counted_cash", "")
    counted = parse_amount(raw)
    try:
        closing = close_cash_day(_cabinet(request), day, counted, request.POST.get("note", ""), request.user)
    except BillingError as error:
        context = _journal_context(request, day, close_error=str(error), counted_input=raw, note_input=request.POST.get("note", ""))
        return render(request, "billing/_cash_journal.html", context)
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
