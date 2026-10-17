"""Réglages issus des réponses de Dr Errmili : espèces seules, pas de partiel, téléphone WhatsApp."""
from django.db import migrations

CABINET_SLUG = "cabinet-dr-errmili"


def apply_settings(apps, schema_editor):
    Cabinet = apps.get_model("accounts", "Cabinet")
    Cabinet.objects.filter(slug=CABINET_SLUG).update(
        modes_paiement=["cash"], paiement_partiel=False, telephone_whatsapp="06 66 54 69 54",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_cabinet_reglages"),
    ]

    operations = [
        migrations.RunPython(apply_settings, migrations.RunPython.noop),
    ]
