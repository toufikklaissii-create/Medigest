"""Certificats et courriers de la consultation : types, champs remplis automatiquement, modèles de départ.

Chaque type est un document de la consultation (Document.document_type = clé ci-dessous, aussi utilisée
dans l'URL d'impression) et s'imprime avec son propre titre sur le papier à en-tête du cabinet.
Données pures (sans import de modèles) : utilisées par la migration 0010, l'installeur et les vues.
"""
import re

from django.utils import timezone
from django.utils.formats import date_format

# clé (= Document.document_type), libellé (menus), titre imprimé, icône Lucide
COURRIER_TYPES = [
    {"key": "certificate", "label": "Certificat médical", "title": "Certificat médical", "icon": "badge-check"},
    {"key": "cert_grossesse", "label": "Certificat de grossesse", "title": "Certificat de grossesse", "icon": "baby"},
    {"key": "arret_travail", "label": "Arrêt de travail", "title": "Certificat d'arrêt de travail", "icon": "calendar-x"},
    {"key": "letter", "label": "Lettre à un confrère", "title": "Lettre à un confrère", "icon": "mail"},
    {"key": "hospitalisation", "label": "Demande d'hospitalisation", "title": "Demande d'hospitalisation", "icon": "bed-double"},
    {"key": "preanesthesia", "label": "Consultation pré-anesthésie", "title": "Consultation pré-anesthésie", "icon": "syringe"},
]
COURRIER_TYPES_BY_KEY = {t["key"]: t for t in COURRIER_TYPES}
COURRIER_TYPE_CHOICES = [(t["key"], t["label"]) for t in COURRIER_TYPES]

# Champs que la doctoresse peut écrire dans ses modèles ; remplis au moment de l'insertion en consultation.
CHAMPS = [
    ("patiente", "Mme Prénom Nom"),
    ("age", "âge de la patiente"),
    ("date_naissance", "date de naissance"),
    ("cin", "numéro de CIN"),
    ("ddr", "date des dernières règles"),
    ("terme", "terme en SA"),
    ("dpa", "date prévue d'accouchement"),
    ("date", "date du jour"),
    ("docteur", "nom de la doctoresse"),
    ("ville", "ville du cabinet"),
]
_CHAMP = re.compile(r"\{(" + "|".join(name for name, _ in CHAMPS) + r")\}")


def _long_date(value):
    return date_format(value, "j F Y") if value else ""


def valeurs_champs(patient, consultation=None, doctor_name="", ville="", today=None):
    """Valeurs des champs ; un champ inconnu reste entre crochets, à compléter à la main."""
    today = today or timezone.localdate()
    pregnancy = consultation.pregnancy if consultation is not None else None
    lmp = consultation.last_menstrual_period if consultation is not None else None
    age = getattr(patient, "age", None)
    return {
        "patiente": f"Mme {patient.first_name} {patient.last_name}".strip(),
        "age": f"{age} ans" if age else "[âge]",
        "date_naissance": _long_date(patient.birth_date) or "[date de naissance]",
        "cin": patient.cin or "[CIN]",
        "ddr": _long_date(lmp) or "[DDR]",
        "terme": f"{pregnancy['weeks']} SA + {pregnancy['days']} j" if pregnancy else "[terme]",
        "dpa": _long_date(pregnancy["due_date"]) if pregnancy else "[date prévue d'accouchement]",
        "date": _long_date(today),
        "docteur": doctor_name or "[nom du médecin]",
        "ville": ville or "[ville]",
    }


def remplir(texte, valeurs):
    """Remplace {patiente}, {ddr}… par leur valeur ; tout autre texte est laissé tel quel."""
    return _CHAMP.sub(lambda match: valeurs[match.group(1)], texte or "")


MODELES_COURRIER_DEFAUT = [
    # ── Certificat médical ────────────────────────────────────────────────────────────────
    {
        "type_document": "certificate", "nom": "Certificat médical simple",
        "contenu": (
            "Je soussignée, {docteur}, certifie avoir examiné ce jour {patiente}, âgée de {age}.\n\n"
            "[Constatations]\n\n"
            "Certificat établi à la demande de l'intéressée et remis en main propre pour servir et valoir ce que de droit."
        ),
    },
    {
        "type_document": "certificate", "nom": "Certificat de prise en charge",
        "contenu": (
            "Je soussignée, {docteur}, certifie que {patiente} est prise en charge dans le cadre d'un suivi "
            "gynécologique / obstétrical au sein de ce cabinet.\n\n"
            "Ce certificat est délivré à la patiente pour faire valoir ce que de droit."
        ),
    },
    {
        "type_document": "certificate", "nom": "Certificat prénuptial",
        "contenu": (
            "Je soussignée, {docteur}, certifie avoir examiné ce jour {patiente}, née le {date_naissance}, "
            "CIN {cin}, dans le cadre de l'examen médical prénuptial.\n\n"
            "L'examen clinique et les examens complémentaires réalisés ne révèlent pas de contre-indication "
            "médicale au mariage.\n\n"
            "Certificat délivré à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    {
        "type_document": "certificate", "nom": "Aptitude au voyage (grossesse)",
        "contenu": (
            "Je soussignée, {docteur}, certifie avoir examiné ce jour {patiente}, enceinte de {terme} "
            "(DDR : {ddr}, terme prévu le {dpa}).\n\n"
            "La grossesse évolue normalement à ce jour. Je ne constate pas de contre-indication médicale "
            "au voyage en avion jusqu'au [date].\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    {
        "type_document": "certificate", "nom": "Dispense de sport",
        "contenu": (
            "Je soussignée, {docteur}, certifie que l'état de santé de {patiente} contre-indique "
            "temporairement la pratique des activités sportives pendant [durée] à compter du {date}.\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    # ── Certificat de grossesse ───────────────────────────────────────────────────────────
    {
        "type_document": "cert_grossesse", "nom": "Déclaration de grossesse",
        "contenu": (
            "Je soussignée, {docteur}, certifie que {patiente}, âgée de {age}, est enceinte.\n\n"
            "Date des dernières règles : {ddr}\n"
            "Terme au {date} : {terme}\n"
            "Date prévue d'accouchement : {dpa}\n\n"
            "Certificat établi à la demande de l'intéressée pour faire valoir ce que de droit."
        ),
    },
    {
        "type_document": "cert_grossesse", "nom": "Grossesse à surveiller (repos)",
        "contenu": (
            "Je soussignée, {docteur}, certifie que {patiente} est enceinte de {terme} "
            "(date prévue d'accouchement : {dpa}).\n\n"
            "Son état nécessite [un repos à domicile / une surveillance rapprochée / l'évitement des efforts "
            "physiques] jusqu'au [date].\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    # ── Arrêt de travail ──────────────────────────────────────────────────────────────────
    {
        "type_document": "arret_travail", "nom": "Arrêt de travail",
        "contenu": (
            "Je soussignée, {docteur}, certifie avoir examiné ce jour {patiente}, âgée de {age}, et que son "
            "état de santé nécessite un arrêt de travail de [nombre] jours, du {date} au [date de fin] inclus, "
            "sauf complications.\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    {
        "type_document": "arret_travail", "nom": "Congé de maternité",
        "contenu": (
            "Je soussignée, {docteur}, certifie que {patiente} est enceinte de {terme}, avec une date prévue "
            "d'accouchement le {dpa}.\n\n"
            "Elle peut bénéficier de son congé de maternité à compter du [date de début].\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    {
        "type_document": "arret_travail", "nom": "Arrêt post-opératoire",
        "contenu": (
            "Je soussignée, {docteur}, certifie que {patiente} a bénéficié le [date] d'une intervention "
            "chirurgicale ([cœlioscopie / hystéroscopie / césarienne / autre]).\n\n"
            "Son état nécessite un arrêt de travail de [nombre] jours à compter du [date], sauf complications.\n\n"
            "Certificat remis à l'intéressée pour servir et valoir ce que de droit."
        ),
    },
    # ── Lettre à un confrère ──────────────────────────────────────────────────────────────
    {
        "type_document": "letter", "nom": "Demande d'avis spécialisé",
        "contenu": (
            "Cher confrère, chère consœur,\n\n"
            "Je vous adresse {patiente}, âgée de {age}, pour avis complémentaire concernant [motif].\n\n"
            "Éléments cliniques : [à compléter]\n"
            "Examens réalisés : [à compléter]\n\n"
            "Je vous remercie de bien vouloir me tenir informée de votre avis.\n\n"
            "Confraternellement,\n{docteur}"
        ),
    },
    {
        "type_document": "letter", "nom": "Échographie morphologique",
        "contenu": (
            "Cher confrère, chère consœur,\n\n"
            "Je vous adresse {patiente}, âgée de {age}, enceinte de {terme} (DDR : {ddr}, terme prévu le {dpa}), "
            "pour la réalisation d'une échographie morphologique du [1er / 2e / 3e] trimestre.\n\n"
            "Particularités : [à compléter]\n\n"
            "Je vous remercie de bien vouloir me transmettre vos conclusions.\n\n"
            "Confraternellement,\n{docteur}"
        ),
    },
    {
        "type_document": "letter", "nom": "Courrier au médecin traitant",
        "contenu": (
            "Cher confrère, chère consœur,\n\n"
            "J'ai vu en consultation le {date} {patiente}, âgée de {age}, pour [motif].\n\n"
            "Examen : [à compléter]\n"
            "Conclusion : [à compléter]\n"
            "Conduite à tenir : [à compléter]\n\n"
            "Bien confraternellement,\n{docteur}"
        ),
    },
    # ── Demande d'hospitalisation ─────────────────────────────────────────────────────────
    {
        "type_document": "hospitalisation", "nom": "Accouchement",
        "contenu": (
            "Je soussignée, {docteur}, demande l'hospitalisation de {patiente}, âgée de {age}, enceinte de "
            "{terme} (terme prévu le {dpa}), pour [accouchement / déclenchement / césarienne programmée] "
            "le [date].\n\n"
            "Groupe sanguin : [à compléter]\n"
            "Antécédents : [à compléter]\n"
            "Particularités de la grossesse : [à compléter]\n\n"
            "{docteur}"
        ),
    },
    {
        "type_document": "hospitalisation", "nom": "Chirurgie programmée",
        "contenu": (
            "Je soussignée, {docteur}, demande l'hospitalisation de {patiente}, âgée de {age}, pour "
            "[cœlioscopie / hystéroscopie / myomectomie / hystérectomie] programmée le [date].\n\n"
            "Indication : [à compléter]\n"
            "Bilan préopératoire : [joint / à réaliser]\n"
            "Consultation d'anesthésie : [date]\n\n"
            "{docteur}"
        ),
    },
    {
        "type_document": "hospitalisation", "nom": "Urgence",
        "contenu": (
            "Je soussignée, {docteur}, adresse en urgence {patiente}, âgée de {age}, pour [métrorragies / "
            "douleurs pelviennes / suspicion de grossesse extra-utérine / menace d'accouchement prématuré].\n\n"
            "Éléments cliniques : [à compléter]\n"
            "Traitement déjà administré : [à compléter]\n\n"
            "{docteur}"
        ),
    },
    # ── Consultation pré-anesthésie ───────────────────────────────────────────────────────
    {
        "type_document": "preanesthesia", "nom": "Consultation pré-anesthésie",
        "contenu": (
            "Compte rendu à l'attention du médecin anesthésiste dans le cadre d'une consultation "
            "pré-anesthésique pour {patiente}, âgée de {age}.\n\n"
            "Antécédents médicaux : [à compléter]\n"
            "Allergies connues : [à compléter]\n"
            "Traitement en cours : [à compléter]\n\n"
            "Intervention prévue : [à compléter]"
        ),
    },
]


def creer_modeles_courrier_defaut(cabinet, model):
    """Crée les modèles de départ pour un cabinet qui n'en a encore aucun ; renvoie le nombre créé.

    Un cabinet qui a déjà des modèles n'est jamais modifié : un modèle supprimé ne revient pas.
    """
    if model.objects.filter(cabinet=cabinet).exists():
        return 0
    model.objects.bulk_create(model(cabinet=cabinet, **data) for data in MODELES_COURRIER_DEFAUT)
    return len(MODELES_COURRIER_DEFAUT)
