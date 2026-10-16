"""Recettes : journal de caisse, clôture, rapports par période et exports comptables.

Base unique : la date d'ENCAISSEMENT (Payment.paid_at) lue dans le fuseau du cabinet
(Africa/Casablanca). Les factures annulées n'apportent aucune recette.
"""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import CashClosing, Invoice, Payment, PaymentMethod
from .services import BillingError

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def cabinet_tz():
    return ZoneInfo(settings.TIME_ZONE)


def local_today():
    return timezone.now().astimezone(cabinet_tz()).date()


def local_date(value):
    return value.astimezone(cabinet_tz()).date()


def day_bounds(start, end=None):
    """[début du jour `start`, début du lendemain de `end`[ en datetimes aware Casablanca."""
    tz = cabinet_tz()
    end = end or start
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
    )


def format_long_date(value):
    """« vendredi 16 octobre 2026 »."""
    return f"{WEEKDAYS[value.weekday()]} {value.day} {MONTHS[value.month - 1]} {value.year}"


def parse_iso_date(value, default=None):
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return default


def period_payments(cabinet, start, end):
    """Encaissements du cabinet entre `start` et `end` inclus (dates locales)."""
    since, until = day_bounds(start, end)
    return (
        Payment.objects.filter(invoice__cabinet=cabinet, paid_at__gte=since, paid_at__lt=until)
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .select_related("invoice__patient", "received_by")
        .order_by("paid_at", "pk")
    )


def totals_by_method(payments):
    totals = OrderedDict((value, ZERO) for value in PaymentMethod.values)
    for payment in payments:
        totals[payment.method] = totals.get(payment.method, ZERO) + payment.amount
    labels = dict(PaymentMethod.choices)
    return [
        {"method": method, "label": labels.get(method, method), "amount": amount}
        for method, amount in totals.items()
    ]


# ── Journal de caisse ────────────────────────────────────────────────────────

def expected_cash(cabinet, day):
    total = period_payments(cabinet, day, day).filter(method=PaymentMethod.CASH).aggregate(s=Sum("amount"))["s"]
    return total or ZERO


def cash_journal(cabinet, day):
    payments = list(period_payments(cabinet, day, day).prefetch_related("invoice__items__act"))
    closing = CashClosing.objects.filter(cabinet=cabinet, date=day).select_related("closed_by").first()
    for payment in payments:
        payment.acts_label = ", ".join(item.act.name for item in payment.invoice.items.all())
        # Encaissement saisi après la clôture de la journée : signalé, jamais bloqué.
        payment.after_closing = bool(closing and payment.created_at > closing.closed_at)
    since, until = day_bounds(day)
    due_invoices = [
        invoice
        for invoice in Invoice.objects.filter(
            cabinet=cabinet, created_at__gte=since, created_at__lt=until,
            status__in=[Invoice.Status.PENDING, Invoice.Status.PARTIAL],
        ).select_related("patient").prefetch_related("payments").order_by("created_at")
        if invoice.balance_due > 0
    ]
    cash = sum((p.amount for p in payments if p.method == PaymentMethod.CASH), ZERO)
    return {
        "day": day,
        "payments": payments,
        "total": sum((p.amount for p in payments), ZERO),
        "by_method": totals_by_method(payments),
        "patients_count": len({p.invoice.patient_id for p in payments}),
        "due_invoices": due_invoices,
        "due_total": sum((i.balance_due for i in due_invoices), ZERO),
        "expected_cash": cash,
        "closing": closing,
        "late_payments": [p for p in payments if p.after_closing],
        # Espèces encaissées depuis la clôture : écart à reporter.
        "cash_since_closing": cash - closing.expected_cash if closing else ZERO,
    }


def close_cash_day(cabinet, day, counted_cash, note, user):
    if counted_cash is None or counted_cash < 0:
        raise BillingError("Saisissez le montant des espèces comptées.")
    if day > local_today():
        raise BillingError("Impossible de clôturer une journée à venir.")
    expected = expected_cash(cabinet, day)
    try:
        with transaction.atomic():
            return CashClosing.objects.create(
                cabinet=cabinet, date=day, expected_cash=expected, counted_cash=counted_cash,
                difference=counted_cash - expected, note=(note or "").strip(), closed_by=user,
            )
    except IntegrityError:
        raise BillingError("Cette journée est déjà clôturée.") from None


def is_day_closed(cabinet, day=None):
    return CashClosing.objects.filter(cabinet=cabinet, date=day or local_today()).exists()


# ── Périodes de rapport ──────────────────────────────────────────────────────

PERIOD_CHOICES = [("jour", "Jour"), ("semaine", "Semaine"), ("mois", "Mois"), ("libre", "Période libre")]
MAX_PERIOD_DAYS = 366


@dataclass
class Period:
    kind: str
    start: date
    end: date

    @property
    def days(self):
        return (self.end - self.start).days + 1

    @property
    def label(self):
        if self.kind == "jour":
            return format_long_date(self.start)
        if self.kind == "mois":
            return f"{MONTHS[self.start.month - 1]} {self.start.year}"
        prefix = "semaine du" if self.kind == "semaine" else "du"
        start_year = f" {self.start.year}" if self.start.year != self.end.year else ""
        return (
            f"{prefix} {self.start.day} {MONTHS[self.start.month - 1]}{start_year}"
            f" au {self.end.day} {MONTHS[self.end.month - 1]} {self.end.year}"
        )

    @property
    def anchor(self):
        """Date de référence du sélecteur : aujourd'hui si la période le contient."""
        today = local_today()
        return today if self.start <= today <= self.end else self.start

    @property
    def slug(self):
        if self.kind == "jour":
            return self.start.isoformat()
        if self.kind == "mois":
            return f"{self.start:%Y-%m}"
        if self.kind == "semaine":
            year, week, _ = self.start.isocalendar()
            return f"{year}-S{week:02d}"
        return f"{self.start.isoformat()}_{self.end.isoformat()}"

    def previous(self):
        if self.kind == "mois":
            end = self.start - timedelta(days=1)
            return Period("mois", end.replace(day=1), end)
        return Period(self.kind, self.start - timedelta(days=self.days), self.start - timedelta(days=1))

    def shifted(self, step):
        """Période voisine (step = -1 / +1) pour la navigation."""
        if self.kind == "mois":
            anchor = self.start.replace(day=1)
            month = anchor.month - 1 + step
            return make_period("mois", date(anchor.year + month // 12, month % 12 + 1, 1))
        return Period(self.kind, self.start + timedelta(days=self.days * step), self.end + timedelta(days=self.days * step))

    def query(self):
        if self.kind == "libre":
            return f"periode=libre&du={self.start.isoformat()}&au={self.end.isoformat()}"
        return f"periode={self.kind}&date={self.start.isoformat()}"


def make_period(kind, anchor, end=None):
    if kind == "jour":
        return Period("jour", anchor, anchor)
    if kind == "semaine":
        start = anchor - timedelta(days=anchor.weekday())
        return Period("semaine", start, start + timedelta(days=6))
    if kind == "libre":
        end = end or anchor
        start, end = min(anchor, end), max(anchor, end)
        end = min(end, start + timedelta(days=MAX_PERIOD_DAYS - 1))
        return Period("libre", start, end)
    start = anchor.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return Period("mois", start, next_month - timedelta(days=1))


def period_from_params(params):
    today = local_today()
    kind = params.get("periode", "mois")
    if kind not in dict(PERIOD_CHOICES):
        kind = "mois"
    if kind == "libre":
        start = parse_iso_date(params.get("du"), today.replace(day=1))
        return make_period("libre", start, parse_iso_date(params.get("au"), today))
    return make_period(kind, parse_iso_date(params.get("date"), today))


# ── Rapport ──────────────────────────────────────────────────────────────────

def _act_breakdown(payments):
    """Recettes par acte : chaque paiement est réparti au prorata des lignes de sa facture.

    La quantité compte une fois chaque acte facturé, dans la période de son premier encaissement.
    La somme des montants par acte égale toujours le total encaissé (arrondi reporté sur la dernière ligne).
    """
    rows = OrderedDict()
    first_ids = {}
    for invoice_id, payment_id in (
        Payment.objects.filter(invoice_id__in={p.invoice_id for p in payments})
        .order_by("invoice_id", "paid_at", "pk").values_list("invoice_id", "pk")
    ):
        first_ids.setdefault(invoice_id, payment_id)

    def bucket(key, label):
        return rows.setdefault(key, {"name": label, "quantity": 0, "amount": ZERO})

    for payment in payments:
        items = list(payment.invoice.items.all())
        subtotal = sum((item.price for item in items), ZERO)
        if not items or subtotal <= 0:
            bucket(None, "Sans acte détaillé")["amount"] += payment.amount
            continue
        remaining = payment.amount
        for index, item in enumerate(items):
            if index == len(items) - 1:
                share = remaining
            else:
                share = (payment.amount * item.price / subtotal).quantize(CENT)
                remaining -= share
            row = bucket(item.act_id, item.act.name)
            row["amount"] += share
            if first_ids.get(payment.invoice_id) == payment.pk:
                row["quantity"] += 1
    return sorted(rows.values(), key=lambda r: (-r["amount"], r["name"]))


def _summary(cabinet, period):
    payments = list(period_payments(cabinet, period.start, period.end).prefetch_related("invoice__items__act"))
    total = sum((p.amount for p in payments), ZERO)
    since, until = day_bounds(period.start, period.end)
    return {
        "payments": payments,
        "total": total,
        "count": len(payments),
        "patients": len({p.invoice.patient_id for p in payments}),
        "average": (total / len(payments)).quantize(CENT) if payments else ZERO,
        "cancelled": Invoice.objects.filter(
            cabinet=cabinet, status=Invoice.Status.CANCELLED, cancelled_at__gte=since, cancelled_at__lt=until
        ).count(),
    }


def _variation(current, previous):
    if not previous:
        return None
    return float((Decimal(current) - Decimal(previous)) / Decimal(previous) * 100)


def outstanding_balance(cabinet):
    invoices = Invoice.objects.filter(
        cabinet=cabinet, status__in=[Invoice.Status.PENDING, Invoice.Status.PARTIAL]
    ).prefetch_related("payments")
    return sum((invoice.balance_due for invoice in invoices), ZERO)


def revenue_report(cabinet, period):
    current = _summary(cabinet, period)
    previous = _summary(cabinet, period.previous())
    payments = current["payments"]

    by_day = OrderedDict()
    for offset in range(period.days):
        day = period.start + timedelta(days=offset)
        by_day[day] = {"date": day, "amount": ZERO, "count": 0}
    for payment in payments:
        row = by_day[local_date(payment.paid_at)]
        row["amount"] += payment.amount
        row["count"] += 1
    days = list(by_day.values())
    peak = max((row["amount"] for row in days), default=ZERO)
    for index, row in enumerate(days):
        # Géométrie du graphique SVG (viewBox de 100 unités par jour × 1000 de haut).
        height = round(float(row["amount"] / peak) * 980) if peak and row["amount"] else 10
        row.update(x=index * 100, bar_x=index * 100 + 18, bar_y=1000 - height, bar_height=height)

    for payment in payments:
        payment.acts_label = ", ".join(item.act.name for item in payment.invoice.items.all())

    return {
        "period": period,
        "previous_period": period.previous(),
        "payments": payments,
        "total": current["total"],
        "count": current["count"],
        "patients": current["patients"],
        "average": current["average"],
        "cancelled": current["cancelled"],
        "outstanding": outstanding_balance(cabinet),
        "previous": {k: v for k, v in previous.items() if k != "payments"},
        "variations": {
            key: _variation(current[key], previous[key]) for key in ("total", "count", "patients", "average")
        },
        "by_method": totals_by_method(payments),
        "by_act": _act_breakdown(payments),
        "by_day": days,
        "peak": peak,
        "chart_width": len(days) * 100,
    }
