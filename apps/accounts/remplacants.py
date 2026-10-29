"""Comptes des médecins remplaçants, gérés par la doctoresse (Réglages → Remplaçants).

Un compte par remplaçant (on sait qui a fait quoi), activable et désactivable à tout moment.
Le remplaçant a accès à tout le clinique, jamais à l'argent (voir MoneyAccessMiddleware).
"""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .decorators import role_required
from .models import Profile


def _remplacants(cabinet):
    return (
        User.objects.filter(profile__cabinet=cabinet, profile__role=Profile.Role.REMPLACANT)
        .order_by("-is_active", "last_name", "first_name")
    )


def _password_errors(password, confirmation, user):
    if not password:
        return ["Choisissez un mot de passe."]
    if password != confirmation:
        return ["Les deux mots de passe sont différents."]
    try:
        validate_password(password, user)
    except ValidationError as error:
        return list(error.messages)
    return []


def suggested_username(first_name, last_name):
    base = slugify(f"dr {last_name or first_name}").replace("-", "_") or "remplacant"
    username, index = base, 2
    while User.objects.filter(username=username).exists():
        username, index = f"{base}{index}", index + 1
    return username


@login_required
@role_required("doctor")
def remplacants(request):
    cabinet = request.user.profile.cabinet
    errors, values = {}, {}
    if request.method == "POST":
        values = {key: request.POST.get(key, "").strip() for key in ("first_name", "last_name", "username")}
        if not values["first_name"] or not values["last_name"]:
            errors["name"] = "Prénom et nom sont obligatoires."
        username = values["username"] or suggested_username(values["first_name"], values["last_name"])
        if not re.fullmatch(r"[\w.@+-]{3,150}", username):
            errors["username"] = "Identifiant : 3 caractères minimum, lettres, chiffres, point ou tiret, sans espace."
        elif User.objects.filter(username__iexact=username).exists():
            errors["username"] = "Cet identifiant est déjà utilisé."
        candidate = User(username=username, first_name=values["first_name"], last_name=values["last_name"])
        password_errors = _password_errors(request.POST.get("password", ""), request.POST.get("password2", ""), candidate)
        if password_errors:
            errors["password"] = " ".join(password_errors)
        if not errors:
            with transaction.atomic():
                candidate.set_password(request.POST["password"])
                candidate.save()
                Profile.objects.update_or_create(
                    user=candidate, defaults={"role": Profile.Role.REMPLACANT, "cabinet": cabinet}
                )
            messages.success(
                request, f"Compte de Dr {candidate.get_full_name()} créé. Identifiant : {candidate.username}."
            )
            return redirect("accounts:remplacants")
    return render(request, "accounts/remplacants.html", {
        "remplacants": _remplacants(cabinet),
        "errors": errors,
        "values": values,
        "login_slug": cabinet.slug if cabinet else "",
    })


def _own_remplacant(request, pk):
    return get_object_or_404(
        User, pk=pk, profile__cabinet=request.user.profile.cabinet, profile__role=Profile.Role.REMPLACANT
    )


@login_required
@role_required("doctor")
@require_POST
def remplacant_toggle(request, pk):
    user = _own_remplacant(request, pk)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    if user.is_active:
        messages.success(request, f"Compte de Dr {user.get_full_name()} réactivé.")
    else:
        messages.success(request, f"Compte de Dr {user.get_full_name()} désactivé : il ne peut plus se connecter.")
    return redirect("accounts:remplacants")


@login_required
@role_required("doctor")
@require_POST
def remplacant_password(request, pk):
    user = _own_remplacant(request, pk)
    errors = _password_errors(request.POST.get("password", ""), request.POST.get("password2", ""), user)
    if errors:
        messages.error(request, f"Mot de passe de Dr {user.get_full_name()} non modifié : {' '.join(errors)}")
    else:
        user.set_password(request.POST["password"])
        user.save(update_fields=["password"])
        messages.success(request, f"Nouveau mot de passe enregistré pour Dr {user.get_full_name()}.")
    return redirect("accounts:remplacants")
