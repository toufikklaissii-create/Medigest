"""Validation des constantes d'accueil saisies par l'assistante (jamais d'erreur 500)."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

WEIGHT_RANGE = (Decimal("25"), Decimal("250"))
HEIGHT_RANGE = (Decimal("120"), Decimal("210"))
# Tension en cmHg (12/8) ou en mmHg (120/80).
BP_PATTERN = re.compile(r"^\s*(\d{1,3}(?:[.,]\d)?)\s*/\s*(\d{1,3}(?:[.,]\d)?)\s*$")
BP_RANGES = {
    "cmHg": ((Decimal("7"), Decimal("25")), (Decimal("4"), Decimal("15"))),
    "mmHg": ((Decimal("70"), Decimal("250")), (Decimal("40"), Decimal("150"))),
}
HISTORY_MAX_LENGTH = 2000


def _decimal(raw):
    try:
        value = Decimal(raw.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _in_range(value, bounds):
    return bounds[0] <= value <= bounds[1]


def _blood_pressure_error(raw):
    match = BP_PATTERN.match(raw)
    if not match:
        return "Format attendu : 12/8 ou 120/80."
    systolic, diastolic = (Decimal(g.replace(",", ".")) for g in match.groups())
    unit = "cmHg" if systolic <= 30 else "mmHg"
    sys_range, dia_range = BP_RANGES[unit]
    if not (_in_range(systolic, sys_range) and _in_range(diastolic, dia_range)) or systolic <= diastolic:
        return "Valeur de tension peu plausible, merci de vérifier."
    return None


def clean_intake_vitals(data, today):
    """Retourne (valeurs nettoyées, erreurs par champ, valeurs brutes à réafficher)."""
    raw = {
        name: (data.get(name) or "").strip()
        for name in ("blood_pressure", "weight_kg", "height_cm", "last_menstrual_period", "medical_history",
                     "medical_history_add", "allergies", "allergies_add")
    }
    cleaned, errors = {}, {}

    cleaned["blood_pressure"] = raw["blood_pressure"]
    if raw["blood_pressure"]:
        error = _blood_pressure_error(raw["blood_pressure"])
        if error:
            errors["blood_pressure"] = error

    for name, bounds, unit, label in (
        ("weight_kg", WEIGHT_RANGE, "kg", "Le poids"),
        ("height_cm", HEIGHT_RANGE, "cm", "La taille"),
    ):
        cleaned[name] = None
        if not raw[name]:
            continue
        value = _decimal(raw[name])
        if value is None:
            errors[name] = f"{label} doit être un nombre (ex. {'68,5' if unit == 'kg' else '165'})."
        elif not _in_range(value, bounds):
            errors[name] = f"{label} doit être compris entre {bounds[0]} et {bounds[1]} {unit}."
        else:
            cleaned[name] = value.quantize(Decimal("0.01") if unit == "kg" else Decimal("0.1"))

    cleaned["last_menstrual_period"] = None
    if raw["last_menstrual_period"]:
        try:
            lmp = date.fromisoformat(raw["last_menstrual_period"])
        except ValueError:
            errors["last_menstrual_period"] = "Date invalide."
        else:
            if lmp > today:
                errors["last_menstrual_period"] = "La DDR ne peut pas être dans le futur."
            else:
                cleaned["last_menstrual_period"] = lmp

    cleaned["medical_history"] = raw["medical_history"]
    for field in ("medical_history", "allergies"):
        for name in (field, field + "_add"):
            if len(raw[name]) > HISTORY_MAX_LENGTH:
                errors[field] = f"{HISTORY_MAX_LENGTH} caractères maximum."

    return cleaned, errors, raw
