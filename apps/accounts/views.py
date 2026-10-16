import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from apps.billing.reports import format_long_date, local_today

from .decorators import role_required
from .models import Cabinet, PrintProfile, Profile
from .printing import build_test_page


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
    if profile and profile.role == Profile.Role.DOCTOR:
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


def _settings_context(cabinet, profiles, errors=None, saved=False):
    return {"cabinet": cabinet, "profiles": profiles, "errors": errors or {}, "saved": saved}


@login_required
@role_required("doctor")
def cabinet_settings(request):
    cabinet = request.user.profile.cabinet
    profiles = PrintProfile.ensure_defaults(cabinet)
    if request.method != "POST":
        return render(request, "accounts/settings.html", _settings_context(cabinet, profiles))

    errors = {}
    for profile in profiles:
        profile_errors = _profile_from_data(profile, request.POST)
        if profile_errors:
            errors[profile.document_type] = " ".join(profile_errors)
    if errors:
        response = render(request, "accounts/_settings_form.html", _settings_context(cabinet, profiles, errors))
        return _toast(response, "Certains décalages sont invalides : corrigez les lignes signalées.", "error")

    cabinet.ville = request.POST.get("ville", "").strip()[:80]
    cabinet.inpe = request.POST.get("inpe", "").strip()[:30]
    cabinet.ice = request.POST.get("ice", "").strip()[:30]
    cabinet.save(update_fields=["ville", "inpe", "ice"])
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
