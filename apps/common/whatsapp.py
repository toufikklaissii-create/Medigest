"""WhatsApp via liens wa.me (aucune API) : nettoyage des numéros et modèles de messages."""

import re
from urllib.parse import quote

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

MOROCCAN_MOBILE = re.compile(r"^212[67]\d{8}$")
INTERNATIONAL = re.compile(r"^[1-9]\d{7,14}$")


def clean_moroccan_phone(raw_phone):
    """Nettoie un numéro pour le format international wa.me (ex: 0612345678 -> 212612345678)."""
    digits = "".join(ch for ch in (raw_phone or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = "212" + digits[1:]
    elif digits.startswith("0") and len(digits) > 10:
        digits = "212" + digits.lstrip("0")
    elif digits.startswith("2120"):
        digits = "212" + digits[4:]
    return digits


def whatsapp_phone(raw_phone):
    """Numéro utilisable par wa.me, ou "" s'il est absent ou à vérifier.

    Accepte un mobile marocain (212 + 6/7 + 8 chiffres) ou un numéro
    international plausible (8 à 15 chiffres, hors Maroc).
    """
    phone = clean_moroccan_phone(raw_phone)
    if MOROCCAN_MOBILE.match(phone):
        return phone
    if not phone.startswith("212") and INTERNATIONAL.match(phone):
        return phone
    return ""


def format_rdv_datetime(dt):
    """Ex : « vendredi 17 octobre à 10h30 » (dt déjà en heure locale)."""
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]} à {dt.hour}h{dt.minute:02d}"


def _cabinet_name(cabinet):
    return getattr(cabinet, "nom", "") or "Le cabinet"


def reminder_message(first_name, cabinet, dt):
    message = (
        f"Bonjour {first_name}, {_cabinet_name(cabinet)} vous rappelle votre rendez-vous "
        f"du {format_rdv_datetime(dt)}. Merci de confirmer votre présence en répondant à ce message."
    )
    phone = (getattr(cabinet, "telephone_whatsapp", "") or "").strip()
    return f"{message}\nPour toute question : {phone}" if phone else message


def confirmation_message(first_name, cabinet, dt):
    return (
        f"Bonjour {first_name}, votre rendez-vous avec {_cabinet_name(cabinet)} est bien enregistré "
        f"pour le {format_rdv_datetime(dt)}. À bientôt."
    )


def rescheduled_message(first_name, cabinet, new_dt):
    return (
        f"Bonjour {first_name}, votre rendez-vous avec {_cabinet_name(cabinet)} a été déplacé "
        f"au {format_rdv_datetime(new_dt)}. Merci de nous confirmer que ce créneau vous convient."
    )


def free_message(first_name, cabinet, text):
    return f"Bonjour {first_name}, {text.strip()}\n— {_cabinet_name(cabinet)}"


def whatsapp_link(raw_phone, message):
    phone = whatsapp_phone(raw_phone)
    if not phone:
        return ""
    return f"https://wa.me/{phone}?text={quote(message)}"
