"""Couverture médicale de la patiente, pour séparer les recettes envoyées au comptable.

« organisme_social » reste un texte libre (précision : mutuelle, n° d'affiliation…) ; la
couverture est un choix fermé qui permet de trier les recettes sans ambiguïté.
"""
import re
import unicodedata

CNOPS = "cnops"
CNSS = "cnss"
AUCUNE = "aucune"
AUTRE = "autre"

COUVERTURE_CHOICES = [
    (CNOPS, "CNOPS"),
    (CNSS, "CNSS"),
    (AUCUNE, "Sans couverture"),
    (AUTRE, "Autre (mutuelle, FAR, assurance…)"),
]
COUVERTURE_LABELS = dict(COUVERTURE_CHOICES)
NON_RENSEIGNEE = "Non renseignée"

# Ordre des groupes dans les rapports et l'export comptable.
GROUPES = [CNOPS, CNSS, AUCUNE, AUTRE, ""]


def libelle(code):
    return COUVERTURE_LABELS.get(code or "", NON_RENSEIGNEE)


def libelle_court(code):
    """Libellé sans précision entre parenthèses (en-têtes d'onglets, badges)."""
    return {AUTRE: "Autre"}.get(code, libelle(code))


def _normaliser(texte):
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


_SANS = {"aucun", "aucune", "sans", "neant", "non", "rien", "pas", "0", "nr", "x"}


def deviner_couverture(texte):
    """Couverture certaine d'après l'ancien texte libre, sinon "" (à vérifier par l'assistante).

    Seuls les cas sans ambiguïté sont classés : un texte qui cite à la fois la CNOPS et la CNSS,
    « AMO » seul (géré par les deux caisses) ou une mutuelle restent à vérifier.
    """
    mots = _normaliser(texte)
    if not mots:
        return ""
    compact = mots.replace(" ", "")
    cnops, cnss = "cnops" in compact, "cnss" in compact
    if cnops and not cnss:
        return CNOPS
    if cnss and not cnops:
        return CNSS
    if cnops and cnss:
        return ""
    premier = mots.split()[0]
    if mots in _SANS or (premier in {"aucun", "aucune", "sans", "neant"}):
        return AUCUNE
    return ""
