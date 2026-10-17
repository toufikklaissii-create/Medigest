"""Antécédents et allergies : la doctoresse lit et modifie tout ; l'assistante ajoute sans voir.

Côté assistante, un POST ne peut qu'AJOUTER une ligne datée à la fin du texte existant :
les champs complets (medical_history, allergies) sont ignorés s'ils sont envoyés.
"""
from django.utils import timezone

FIELDS = ("medical_history", "allergies")
ADD_SUFFIX = "_add"
MAX_ADDITION_LENGTH = 1000


def append_note(existing, addition, day=None):
    """« texte existant\n[16/10/2026] ajout » ; inchangé si l'ajout est vide."""
    addition = (addition or "").strip()
    if not addition:
        return existing or ""
    day = day or timezone.localdate()
    line = f"[{day:%d/%m/%Y}] {addition[:MAX_ADDITION_LENGTH]}"
    existing = (existing or "").rstrip()
    return f"{existing}\n{line}" if existing else line


def apply_history_post(patient, data, is_doctor):
    """Applique antécédents / allergies du POST sur `patient` (non sauvegardé). Renvoie les champs modifiés."""
    changed = []
    for field in FIELDS:
        if is_doctor:
            if field in data:
                setattr(patient, field, (data.get(field) or "").strip())
                changed.append(field)
            continue
        addition = data.get(field + ADD_SUFFIX, "")
        if addition.strip():
            setattr(patient, field, append_note(getattr(patient, field), addition))
            changed.append(field)
    return changed
