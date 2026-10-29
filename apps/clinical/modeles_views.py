"""Réglages → Modèles d'ordonnance : la doctoresse crée ses modèles par symptomatologie.

Réservé au rôle médecin (décorateur + préfixe /clinical/ protégé par ClinicalAccessMiddleware).
Toutes les actions passent par HTMX : la carte modifiée est remplacée sur place, avec un toast.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required

from .courriers import CHAMPS, COURRIER_TYPES, COURRIER_TYPES_BY_KEY
from .models import ModeleCourrier, ModeleOrdonnance

TEXT_FIELDS = ("medicaments", "bilan_biologique", "radiologie")
NAME_MAX = ModeleOrdonnance._meta.get_field("nom").max_length
TEXT_MAX = 4000


def _toast(response, message, type_="success", **events):
    response.headers["HX-Trigger"] = json.dumps({"toast": {"message": message, "type": type_}, **events})
    return response


def _cabinet_modeles(request):
    return ModeleOrdonnance.objects.filter(cabinet=request.user.profile.cabinet)


def _modele_from_post(request, modele):
    """Copie le formulaire sur le modèle ; renvoie les erreurs par champ (dict vide si tout va bien)."""
    errors = {}
    modele.nom = " ".join(request.POST.get("nom", "").split())[:NAME_MAX]
    for field in TEXT_FIELDS:
        setattr(modele, field, request.POST.get(field, "").strip()[:TEXT_MAX])
    modele.actif = request.POST.get("actif") == "on"
    if not modele.nom:
        errors["nom"] = "Indiquez la symptomatologie (ex. Mycose vaginale)."
    elif _cabinet_modeles(request).filter(nom__iexact=modele.nom).exclude(pk=modele.pk).exists():
        errors["nom"] = "Un modèle porte déjà ce nom."
    if not errors and modele.is_empty:
        errors["parties"] = "Remplissez au moins une partie : médicaments, bilan biologique ou radiologie."
    return errors


@login_required
@role_required("doctor")
def modeles_ordonnance(request):
    return render(request, "doctor/modeles_ordonnance.html", {"modeles": _cabinet_modeles(request)})


@login_required
@role_required("doctor")
@require_POST
def modele_add(request):
    modele = ModeleOrdonnance(cabinet=request.user.profile.cabinet)
    errors = _modele_from_post(request, modele)
    if not errors:
        try:
            modele.save()
        except IntegrityError:
            errors = {"nom": "Un modèle porte déjà ce nom."}
    if errors:
        response = render(request, "doctor/_modele_add_form.html", {"errors": errors, "form": request.POST})
        response.headers["HX-Retarget"] = "#modele-add-form"
        response.headers["HX-Reswap"] = "outerHTML"
        return _toast(response, "Le modèle n'a pas été ajouté : corrigez les champs signalés.", "error")
    response = render(request, "doctor/_modele_card.html", {"modele": modele, "flash": True})
    return _toast(response, f"Modèle « {modele.nom} » ajouté.", **{"modele-added": True})


@login_required
@role_required("doctor")
def modele_card(request, pk):
    """GET : carte en lecture (?edit=1 : en édition). POST : enregistre la carte."""
    modele = get_object_or_404(_cabinet_modeles(request), pk=pk)
    if request.method != "POST":
        template = "doctor/_modele_card_edit.html" if request.GET.get("edit") else "doctor/_modele_card.html"
        return render(request, template, {"modele": modele})
    errors = _modele_from_post(request, modele)
    if not errors:
        try:
            modele.save()
        except IntegrityError:
            errors = {"nom": "Un modèle porte déjà ce nom."}
    if errors:
        return render(request, "doctor/_modele_card_edit.html", {"modele": modele, "errors": errors})
    response = render(request, "doctor/_modele_card.html", {"modele": modele, "flash": True})
    return _toast(response, f"Modèle « {modele.nom} » enregistré.")


@login_required
@role_required("doctor")
@require_POST
def modele_duplicate(request, pk):
    source = get_object_or_404(_cabinet_modeles(request), pk=pk)
    base = f"{source.nom} (copie)"[:NAME_MAX]
    nom, index = base, 2
    while _cabinet_modeles(request).filter(nom__iexact=nom).exists():
        nom = f"{source.nom} (copie {index})"[:NAME_MAX]
        index += 1
    copie = ModeleOrdonnance.objects.create(
        cabinet=source.cabinet, nom=nom, actif=source.actif,
        **{field: getattr(source, field) for field in TEXT_FIELDS},
    )
    response = render(request, "doctor/_modele_card_edit.html", {"modele": copie})
    return _toast(response, f"Copie créée : renommez « {copie.nom} » puis enregistrez.")


@login_required
@role_required("doctor")
@require_POST
def modele_delete(request, pk):
    modele = get_object_or_404(_cabinet_modeles(request), pk=pk)
    nom = modele.nom
    modele.delete()
    remaining = _cabinet_modeles(request).exists()
    return _toast(HttpResponse(""), f"Modèle « {nom} » supprimé.", **({} if remaining else {"modeles-vides": True}))


# ── Modèles de certificats et courriers ─────────────────────────────────────────────────────

def _cabinet_courriers(request):
    return ModeleCourrier.objects.filter(cabinet=request.user.profile.cabinet)


def _courrier_from_post(request, modele):
    errors = {}
    modele.type_document = request.POST.get("type_document", "")
    modele.nom = " ".join(request.POST.get("nom", "").split())[:NAME_MAX]
    modele.contenu = request.POST.get("contenu", "").strip()[:TEXT_MAX * 2]
    modele.actif = request.POST.get("actif") == "on"
    if modele.type_document not in COURRIER_TYPES_BY_KEY:
        errors["type_document"] = "Choisissez le type de document."
    if not modele.nom:
        errors["nom"] = "Donnez un nom au modèle (ex. Arrêt de travail 7 jours)."
    elif (
        _cabinet_courriers(request)
        .filter(type_document=modele.type_document, nom__iexact=modele.nom).exclude(pk=modele.pk).exists()
    ):
        errors["nom"] = "Un modèle de ce type porte déjà ce nom."
    if not modele.contenu:
        errors["contenu"] = "Écrivez le texte du modèle."
    return errors


def _courrier_context(**extra):
    return {"courrier_types": COURRIER_TYPES, "champs": CHAMPS, **extra}


def _courrier_groups(modeles):
    by_type = {}
    for modele in modeles:
        by_type.setdefault(modele.type_document, []).append(modele)
    return [{**t, "modeles": by_type.get(t["key"], [])} for t in COURRIER_TYPES]


@login_required
@role_required("doctor")
def modeles_courrier(request):
    return render(request, "doctor/modeles_courrier.html",
                  _courrier_context(groups=_courrier_groups(_cabinet_courriers(request))))


@login_required
@role_required("doctor")
@require_POST
def courrier_add(request):
    modele = ModeleCourrier(cabinet=request.user.profile.cabinet)
    errors = _courrier_from_post(request, modele)
    if not errors:
        try:
            modele.save()
        except IntegrityError:
            errors = {"nom": "Un modèle de ce type porte déjà ce nom."}
    if errors:
        response = render(request, "doctor/_courrier_add_form.html",
                          _courrier_context(errors=errors, form=request.POST))
        response.headers["HX-Retarget"] = "#courrier-add-form"
        response.headers["HX-Reswap"] = "outerHTML"
        return _toast(response, "Le modèle n'a pas été ajouté : corrigez les champs signalés.", "error")
    response = render(request, "doctor/_courrier_card.html", _courrier_context(modele=modele, flash=True))
    response.headers["HX-Retarget"] = f"#courriers-{modele.type_document}"
    response.headers["HX-Reswap"] = "afterbegin"
    return _toast(response, f"Modèle « {modele.nom} » ajouté.", **{"courrier-added": modele.type_document})


@login_required
@role_required("doctor")
def courrier_card(request, pk):
    """GET : carte en lecture (?edit=1 : en édition). POST : enregistre la carte."""
    modele = get_object_or_404(_cabinet_courriers(request), pk=pk)
    if request.method != "POST":
        template = "doctor/_courrier_card_edit.html" if request.GET.get("edit") else "doctor/_courrier_card.html"
        return render(request, template, _courrier_context(modele=modele))
    previous_type = modele.type_document
    errors = _courrier_from_post(request, modele)
    if not errors:
        try:
            modele.save()
        except IntegrityError:
            errors = {"nom": "Un modèle de ce type porte déjà ce nom."}
    if errors:
        return render(request, "doctor/_courrier_card_edit.html", _courrier_context(modele=modele, errors=errors))
    response = render(request, "doctor/_courrier_card.html", _courrier_context(modele=modele, flash=True))
    if modele.type_document != previous_type:
        # Type changé : la carte change de rubrique, on recharge la page (rare).
        response.headers["HX-Refresh"] = "true"
    return _toast(response, f"Modèle « {modele.nom} » enregistré.")


@login_required
@role_required("doctor")
@require_POST
def courrier_duplicate(request, pk):
    source = get_object_or_404(_cabinet_courriers(request), pk=pk)
    nom, index = f"{source.nom} (copie)"[:NAME_MAX], 2
    while _cabinet_courriers(request).filter(type_document=source.type_document, nom__iexact=nom).exists():
        nom = f"{source.nom} (copie {index})"[:NAME_MAX]
        index += 1
    copie = ModeleCourrier.objects.create(
        cabinet=source.cabinet, type_document=source.type_document, nom=nom, contenu=source.contenu, actif=source.actif,
    )
    response = render(request, "doctor/_courrier_card_edit.html", _courrier_context(modele=copie))
    response.headers["HX-Retarget"] = f"#courriers-{copie.type_document}"
    response.headers["HX-Reswap"] = "afterbegin"
    return _toast(response, f"Copie créée : renommez « {copie.nom} » puis enregistrez.")


@login_required
@role_required("doctor")
@require_POST
def courrier_delete(request, pk):
    modele = get_object_or_404(_cabinet_courriers(request), pk=pk)
    nom = modele.nom
    modele.delete()
    return _toast(HttpResponse(""), f"Modèle « {nom} » supprimé.")
