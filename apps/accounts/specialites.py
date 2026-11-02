"""Spécialités des cabinets : libellé affiché, actes de départ et modèles proposés à l'installation.

Le module gynécologie (DDR, terme, certificats de grossesse, modèles d'ordonnance) reste
réservé aux cabinets de gynécologie-obstétrique ; les autres reçoivent une base générique.
"""
GYNECOLOGIE = "gynecologie"
GENERALISTE = "generaliste"
PEDIATRIE = "pediatrie"
DENTAIRE = "dentaire"
AUTRE = "autre"

SPECIALITE_CHOICES = [
    (GYNECOLOGIE, "Gynécologie & Obstétrique"),
    (GENERALISTE, "Médecine générale"),
    (PEDIATRIE, "Pédiatrie"),
    (DENTAIRE, "Chirurgie dentaire"),
    (AUTRE, "Autre spécialité"),
]
SPECIALITE_LABELS = dict(SPECIALITE_CHOICES)

# code, libellé, examen rapide, prix libre. Le prix de la consultation est demandé à l'installation ;
# les autres actes sont en prix libre jusqu'à ce que le médecin fixe ses tarifs.
ACTES_DE_DEPART = {
    GYNECOLOGIE: [
        ("CONS_GYN", "Consultation gynécologique", False, False),
        ("ECHO_OBST", "Échographie obstétricale", False, True),
        ("ECHO_PELV", "Échographie pelvienne", False, True),
        ("FROTTIS", "Frottis cervico-vaginal", True, True),
        ("STERILET", "Pose stérilet", False, True),
        ("PRELEV_BACT", "Prélèvement bactériologique", True, True),
        ("POSE_SONDE", "Pose de sonde vésicale", True, True),
    ],
    GENERALISTE: [
        ("CONS", "Consultation", False, False),
        ("CERTIF", "Certificat médical", False, True),
        ("INJECTION", "Injection", True, True),
        ("PANSEMENT", "Pansement", True, True),
        ("ECG", "Électrocardiogramme (ECG)", True, True),
    ],
    PEDIATRIE: [
        ("CONS_PED", "Consultation pédiatrique", False, False),
        ("VACCIN", "Vaccination", True, True),
        ("CERTIF", "Certificat médical", False, True),
        ("NEBUL", "Nébulisation", True, True),
    ],
    DENTAIRE: [
        ("CONS_DENT", "Consultation dentaire", False, False),
        ("DETARTRAGE", "Détartrage", False, True),
        ("EXTRACTION", "Extraction", False, True),
        ("SOIN_CARIE", "Soin de carie", False, True),
        ("RADIO_PANO", "Radiographie panoramique", True, True),
    ],
    AUTRE: [
        ("CONS", "Consultation", False, False),
    ],
}


def libelle(code):
    return SPECIALITE_LABELS.get(code, "")


def actes_de_depart(code):
    return ACTES_DE_DEPART.get(code, ACTES_DE_DEPART[AUTRE])
