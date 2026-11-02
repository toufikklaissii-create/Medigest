"""Rattachement obligatoire au cabinet (multi-cabinet).

Utilisé par les migrations qui rendent `cabinet` obligatoire : chaque ligne encore sans
cabinet le reprend de sa patiente (ou de son RDV) ; s'il n'y a qu'un cabinet dans la base
(installation locale), il le reçoit. Sinon la migration s'arrête avec un message clair plutôt
que de deviner, et l'installeur revient à la version précédente.
"""


def fill_missing_cabinet(apps, app_label, model_name, sources=("patient",)):
    Model = apps.get_model(app_label, model_name)
    Cabinet = apps.get_model("accounts", "Cabinet")
    orphans = Model.objects.filter(cabinet__isnull=True)
    if not orphans.exists():
        return
    for source in sources:
        for obj in orphans.select_related(source):
            related = getattr(obj, source, None)
            cabinet_id = getattr(related, "cabinet_id", None)
            if cabinet_id:
                Model.objects.filter(pk=obj.pk).update(cabinet_id=cabinet_id)
        orphans = Model.objects.filter(cabinet__isnull=True)
    remaining = orphans.count()
    if not remaining:
        return
    cabinets = list(Cabinet.objects.values_list("pk", flat=True)[:2])
    if len(cabinets) == 1:
        orphans.update(cabinet_id=cabinets[0])
        return
    raise RuntimeError(
        f"{remaining} ligne(s) de {model_name} sans cabinet et impossible de deviner lequel : "
        "à rattacher à la main avant la mise à jour."
    )
