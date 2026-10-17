"""Tarifs de Dr Errmili : la consultation à 300 DH (prix fixe), tous les autres actes en prix libre."""
from decimal import Decimal

from django.db import migrations

CABINET_SLUG = "cabinet-dr-errmili"
CONSULTATION_PRICE = Decimal("300")


def apply_tariffs(apps, schema_editor):
    MedicalAct = apps.get_model("billing", "MedicalAct")
    acts = MedicalAct.objects.filter(cabinet__slug=CABINET_SLUG)
    consultation = (
        acts.filter(name__istartswith="consultation").order_by("pk").first()
        or acts.filter(code__istartswith="CONS").order_by("pk").first()
    )
    acts.update(prix_libre=True)
    if consultation is not None:
        consultation.price = CONSULTATION_PRICE
        consultation.prix_libre = False
        consultation.save(update_fields=["price", "prix_libre"])


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0009_cabinet_reglages"),
        ("accounts", "0011_cabinet_errmili_reglages"),
    ]

    operations = [
        migrations.RunPython(apply_tariffs, migrations.RunPython.noop),
    ]
