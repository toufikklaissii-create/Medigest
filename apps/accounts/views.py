import json
from datetime import time
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.billing.reports import format_long_date, local_today

from .decorators import role_required
from .models import Cabinet, PrintProfile, Profile
from .printing import build_test_page
from .specialites import SPECIALITE_CHOICES, SPECIALITE_LABELS


def tenant_discovery(request):
    error = None
    if request.method == "POST":
        raw_slug = request.POST.get("slug", "").strip()
        cabinet = Cabinet.objects.filter(slug=slugify(raw_slug), actif=True).first()
        if cabinet:
            return redirect("tenant_login", slug=cabinet.slug)
        error = "Espace introuvable."
    return render(request, "accounts/discovery.html", {"error": error})


class TenantLoginView(LoginView):
    template_name = "accounts/login.html"

    def dispatch(self, request, *args, **kwargs):
        self.cabinet = get_object_or_404(Cabinet, slug=kwargs["slug"], actif=True)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cabinet"] = self.cabinet
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = getattr(form.get_user(), "profile", None)
        if not profile or profile.cabinet_id != self.cabinet.id:
            logout(self.request)
            form.add_error(None, "Vous n'appartenez pas à ce cabinet.")
            return self.form_invalid(form)
        return response

    def get_success_url(self):
        return "/accounts/redirect/"


tenant_login = TenantLoginView.as_view()


class AccountLogoutView(LogoutView):
    next_page = "accounts:login"


@login_required
def post_login_redirect(request):
    profile = getattr(request.user, "profile", None)
    if profile and profile.is_clinician:
        return redirect("clinical:doctor_dashboard")
    return redirect("appointments:assistant_dashboard")


# ── Réglages du cabinet (doctoresse uniquement) ──────────────────────────────

MAX_OFFSET_MM = Decimal("20")


def _parse_offset(value):
    """« 1,5 » → Decimal('1.5') ; None si illisible ou hors ±20 mm."""
    text = str(value or "0").strip().replace(",", ".") or "0"
    try:
        offset = Decimal(text).quantize(Decimal("0.1"))
    except InvalidOperation:
        return None
    return offset if offset.is_finite() and abs(offset) <= MAX_OFFSET_MM else None


def _profile_from_data(profile, data):
    """Applique les champs « <type>-format / -x / -y » de `data` ; renvoie les erreurs du profil."""
    prefix = profile.document_type
    errors = []
    page_format = data.get(f"{prefix}-format", profile.format)
    if page_format in PrintProfile.Format.values:
        profile.format = page_format
    for axis, attr in (("x", "decalage_x_mm"), ("y", "decalage_y_mm")):
        if f"{prefix}-{axis}" not in data:
            continue
        offset = _parse_offset(data.get(f"{prefix}-{axis}"))
        if offset is None:
            errors.append(f"Décalage {axis.upper()} invalide (entre -20 et 20 mm).")
        else:
            setattr(profile, attr, offset)
    return errors


PAYMENT_METHOD_LABELS = [("cash", "Espèces"), ("card", "Carte"), ("check", "Chèque"), ("transfer", "Virement")]
CABINET_SETTINGS_FIELDS = [
    "ville", "inpe", "ice", "specialite", "adresse", "telephone", "modes_paiement", "paiement_partiel", "heure_ouverture", "heure_fermeture",
    "heure_fermeture_samedi", "dimanche_ferme", "controle_gratuit_jours", "telephone_whatsapp",
]


def _parse_time(value):
    try:
        return time.fromisoformat(str(value or "").strip()[:5])
    except ValueError:
        return None


def _cabinet_from_data(cabinet, data):
    """Applique les réglages du cabinet (POST complet du formulaire) ; renvoie {champ: erreur}."""
    errors = {}
    cabinet.ville = data.get("ville", "").strip()[:80]
    cabinet.inpe = data.get("inpe", "").strip()[:30]
    cabinet.ice = data.get("ice", "").strip()[:30]
    if "adresse" in data:
        cabinet.adresse = data.get("adresse", "").strip()[:200]
        cabinet.telephone = data.get("telephone", "").strip()[:30]
    if data.get("specialite") in SPECIALITE_LABELS:
        cabinet.specialite = data["specialite"]
    if "reglages_cabinet" not in data:
        return errors  # ancien formulaire : seulement les mentions

    modes = [value for value, _ in PAYMENT_METHOD_LABELS if value in data.getlist("modes_paiement")]
    if modes:
        cabinet.modes_paiement = modes
    else:
        errors["modes_paiement"] = "Activez au moins un mode de paiement."
    cabinet.paiement_partiel = data.get("paiement_partiel") == "on"
    cabinet.dimanche_ferme = data.get("dimanche_ferme") == "on"

    for field in ("heure_ouverture", "heure_fermeture", "heure_fermeture_samedi"):
        value = _parse_time(data.get(field))
        if value is None:
            errors["horaires"] = "Heure invalide : format attendu 09:00."
        else:
            setattr(cabinet, field, value)
    if "horaires" not in errors and not (
        cabinet.heure_ouverture < cabinet.heure_fermeture and cabinet.heure_ouverture < cabinet.heure_fermeture_samedi
    ):
        errors["horaires"] = "La fermeture doit être après l'ouverture."

    try:
        days = int(data.get("controle_gratuit_jours", ""))
    except ValueError:
        days = -1
    if 0 <= days <= 365:
        cabinet.controle_gratuit_jours = days
    else:
        errors["controle_gratuit_jours"] = "Entre 0 et 365 jours (0 : désactivé)."
    cabinet.telephone_whatsapp = data.get("telephone_whatsapp", "").strip()[:30]
    return errors


def _settings_context(cabinet, profiles, errors=None, saved=False):
    return {
        "cabinet": cabinet, "profiles": profiles, "errors": errors or {}, "saved": saved,
        "payment_method_labels": PAYMENT_METHOD_LABELS,
        "specialite_choices": SPECIALITE_CHOICES,
        "letterheads": [
            ("entete_pdf", "Papier à en-tête", cabinet.entete_pdf),
            ("entete_ordonnance_pdf", "Modèle d'ordonnance", cabinet.entete_ordonnance_pdf),
        ],
    }


@login_required
@role_required("doctor")
def cabinet_settings(request):
    cabinet = request.user.profile.cabinet
    profiles = PrintProfile.ensure_defaults(cabinet)
    if request.method != "POST":
        return render(request, "accounts/settings.html", _settings_context(cabinet, profiles))

    errors = _cabinet_from_data(cabinet, request.POST)
    for profile in profiles:
        profile_errors = _profile_from_data(profile, request.POST)
        if profile_errors:
            errors[profile.document_type] = " ".join(profile_errors)
    if errors:
        response = render(request, "accounts/_settings_form.html", _settings_context(cabinet, profiles, errors))
        return _toast(response, "Certains réglages sont invalides : corrigez les champs signalés.", "error")

    cabinet.save(update_fields=CABINET_SETTINGS_FIELDS)
    for profile in profiles:
        profile.save()
    response = render(request, "accounts/_settings_form.html", _settings_context(cabinet, profiles, saved=True))
    return _toast(response, "Réglages enregistrés.")


@login_required
@role_required("doctor")
def print_test_page(request, document_type):
    """Page de test du profil ; les valeurs en cours de saisie (GET) priment sur l'enregistré."""
    if document_type not in PrintProfile.DocumentType.values:
        raise Http404("Type de document inconnu.")
    cabinet = request.user.profile.cabinet
    profile = PrintProfile.for_document(cabinet, document_type)
    _profile_from_data(profile, request.GET)
    response = HttpResponse(build_test_page(profile, format_long_date(local_today()).split(" ", 1)[1]),
                            content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="page_de_test_{document_type}.pdf"'
    return response


def _toast(response, message, type_="success"):
    response.headers["HX-Trigger"] = json.dumps({"toast": {"message": message, "type": type_}})
    return response


# ── Papier à en-tête du cabinet ──────────────────────────────────────────────

MAX_LETTERHEAD_BYTES = 5 * 1024 * 1024
LETTERHEAD_FIELDS = {"entete_pdf": "papier à en-tête", "entete_ordonnance_pdf": "modèle d'ordonnance"}


def _letterhead_error(upload):
    """Message d'erreur si le fichier n'est pas un PDF d'une page lisible, sinon None."""
    from pypdf import PdfReader

    if upload.size > MAX_LETTERHEAD_BYTES:
        return "fichier trop lourd (5 Mo maximum)"
    head = upload.read(5)
    upload.seek(0)
    if head != b"%PDF-":
        return "ce n'est pas un fichier PDF"
    try:
        reader = PdfReader(upload)
        pages = len(reader.pages)
    except Exception:  # noqa: BLE001 — PDF illisible, quelle qu'en soit la raison
        return "PDF illisible"
    finally:
        upload.seek(0)
    if pages < 1:
        return "PDF vide"
    return None


@login_required
@role_required("doctor")
def cabinet_letterhead(request):
    """Charge, remplace ou retire le papier à en-tête (POST multipart depuis les Réglages)."""
    if request.method != "POST":
        return redirect("accounts:settings")
    cabinet = request.user.profile.cabinet
    for field, label in LETTERHEAD_FIELDS.items():
        current = getattr(cabinet, field)
        if request.POST.get(f"{field}-supprimer") == "1" and current:
            current.delete(save=False)
            setattr(cabinet, field, "")
            messages.success(request, f"{label.capitalize()} retiré : l'en-tête généré par Medigest est utilisé.")
        upload = request.FILES.get(field)
        if upload:
            error = _letterhead_error(upload)
            if error:
                messages.error(request, f"{label.capitalize()} refusé : {error}.")
                continue
            if current:
                current.delete(save=False)
            getattr(cabinet, field).save(f"{cabinet.slug}_{field}.pdf", upload, save=False)
            messages.success(request, f"{label.capitalize()} enregistré. Vérifiez l'aperçu avant d'imprimer.")
    cabinet.save(update_fields=list(LETTERHEAD_FIELDS))
    return redirect(f"{reverse('accounts:settings')}#entete")


@login_required
@role_required("doctor")
def letterhead_preview(request, kind):
    """Aperçu d'un certificat (ou d'une ordonnance) d'exemple sur le papier du cabinet."""
    from apps.clinical.services import (
        MODE_LETTERHEAD, PRESCRIPTION_LETTERHEAD, doctor_display_name, prescription_lines, render_document,
    )
    from apps.patients.models import Patient

    if kind not in ("certificat", "ordonnance"):
        raise Http404("Aperçu inconnu.")
    cabinet = request.user.profile.cabinet
    patient = Patient(cabinet=cabinet, first_name="Prénom", last_name="EXEMPLE", patient_number="PAT-0000-0000")
    context = {
        "patient": patient, "cabinet": cabinet, "doc_date": timezone.now(),
        "doctor_name": doctor_display_name(request.user),
    }
    if kind == "ordonnance":
        pdf = render_document(
            "pdf/prescription.html",
            {**context, "prescription_lines": prescription_lines("Médicament d'exemple 1 cp matin et soir\nDeuxième ligne d'exemple")},
            cabinet=cabinet, document_type=PrintProfile.DocumentType.ORDONNANCE, mode=MODE_LETTERHEAD,
            background=PRESCRIPTION_LETTERHEAD,
        )
    else:
        pdf = render_document(
            "pdf/letter.html",
            {**context, "doc_title": "Certificat médical",
             "content": "Texte d'exemple : vérifiez que l'en-tête, la date et ce texte ne se chevauchent pas."},
            cabinet=cabinet, document_type=PrintProfile.DocumentType.LETTRE, mode=MODE_LETTERHEAD,
        )
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="apercu_{kind}.pdf"'
    return response
