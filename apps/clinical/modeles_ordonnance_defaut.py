"""Modèles d'ordonnance proposés au départ (anciens modèles « en 1 clic »), rangés par partie.

Données pures : utilisées par la migration 0009 et par la commande installer_cabinet. La doctoresse
les modifie ou les supprime ensuite librement depuis Réglages → Modèles d'ordonnance.
"""

MODELES_DEFAUT = [
    {
        "nom": "Suivi grossesse T1/T2",
        "medicaments": (
            "Acide folique 0,4 mg — 1 comprimé par jour\n"
            "Supplémentation vitamino-calcique — 1 comprimé par jour pendant 1 mois\n"
            "Repos relatif, hydratation abondante"
        ),
        "bilan_biologique": "",
        "radiologie": "Échographie de datation/morphologique à programmer selon le terme",
    },
    {
        "nom": "Infection gynécologique",
        "medicaments": (
            "Ovules antifongiques — 1 ovule au coucher pendant 3 jours\n"
            "Toilette intime avec savon à pH neutre, 2 fois par jour\n"
            "Éviter les rapports pendant le traitement\n"
            "Consultation de contrôle dans 2 semaines si persistance des symptômes"
        ),
        "bilan_biologique": "",
        "radiologie": "",
    },
    {
        "nom": "Bilan préconceptionnel",
        "medicaments": "Acide folique 0,4 mg — 1 comprimé par jour dès le désir de grossesse",
        "bilan_biologique": (
            "NFS, glycémie à jeun, groupe sanguin et rhésus\n"
            "Sérologies : toxoplasmose, rubéole, syphilis, VIH, hépatites B et C\n"
            "TSH\n"
            "Frottis cervico-vaginal si non à jour"
        ),
        "radiologie": "",
    },
]


def creer_modeles_defaut(cabinet, model):
    """Crée les modèles de départ pour un cabinet qui n'en a encore aucun ; renvoie le nombre créé.

    Un cabinet qui a déjà des modèles n'est jamais modifié : un modèle supprimé par la doctoresse
    ne revient pas à la mise à jour suivante.
    """
    if model.objects.filter(cabinet=cabinet).exists():
        return 0
    model.objects.bulk_create(model(cabinet=cabinet, **data) for data in MODELES_DEFAUT)
    return len(MODELES_DEFAUT)
