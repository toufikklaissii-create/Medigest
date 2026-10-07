from urllib.parse import quote


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
    return digits


def appointment_reminder_link(patient, date_display, time_display):
    phone = clean_moroccan_phone(getattr(patient, "phone", ""))
    if not phone:
        return ""
    message = (
        f"Bonjour {patient.first_name}, le Cabinet du Dr ERRMILI vous rappelle votre "
        f"rendez-vous prévu le {date_display} à {time_display}. "
        "Merci de confirmer votre présence."
    )
    return f"https://wa.me/{phone}?text={quote(message)}"
