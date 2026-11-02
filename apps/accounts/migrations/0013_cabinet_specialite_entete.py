from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import migrations, models

ERRMILI = "cabinet-dr-errmili"
STATIC_PDF = Path(settings.BASE_DIR) / "static" / "pdf"


def papier_errmili(apps, schema_editor):
    """Le papier du Dr Errmili, jusqu'ici commun à toute l'installation, devient le sien.

    Les autres cabinets existants (spécialité par défaut : gynécologie) n'ont pas de papier :
    Medigest leur génère un en-tête sobre.
    """
    Cabinet = apps.get_model("accounts", "Cabinet")
    for cabinet in Cabinet.objects.filter(slug=ERRMILI):
        for field, filename in (("entete_pdf", "entete_cabinet.pdf"), ("entete_ordonnance_pdf", "ordonnance_modele.pdf")):
            source = STATIC_PDF / filename
            if not getattr(cabinet, field) and source.exists():
                with source.open("rb") as handle:
                    getattr(cabinet, field).save(f"{ERRMILI}_{filename}", File(handle), save=False)
        cabinet.save()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_role_remplacant"),
    ]

    operations = [
        migrations.AddField(
            model_name="cabinet",
            name="adresse",
            field=models.CharField(blank=True, max_length=200, verbose_name="Adresse"),
        ),
        migrations.AddField(
            model_name="cabinet",
            name="entete_ordonnance_pdf",
            field=models.FileField(
                blank=True,
                help_text="Facultatif : sinon le papier à en-tête sert aussi pour les ordonnances.",
                upload_to="cabinets/entetes/",
                verbose_name="Modèle d'ordonnance (PDF)",
            ),
        ),
        migrations.AddField(
            model_name="cabinet",
            name="entete_pdf",
            field=models.FileField(
                blank=True,
                help_text="Une page A4 : en-tête et pied du cabinet, zone centrale vide.",
                upload_to="cabinets/entetes/",
                verbose_name="Papier à en-tête (PDF)",
            ),
        ),
        migrations.AddField(
            model_name="cabinet",
            name="specialite",
            field=models.CharField(
                choices=[
                    ("gynecologie", "Gynécologie & Obstétrique"),
                    ("generaliste", "Médecine générale"),
                    ("pediatrie", "Pédiatrie"),
                    ("dentaire", "Chirurgie dentaire"),
                    ("autre", "Autre spécialité"),
                ],
                default="gynecologie",
                help_text="Affichée sous le nom du cabinet ; décide des actes et modèles proposés.",
                max_length=20,
                verbose_name="Spécialité",
            ),
        ),
        migrations.AddField(
            model_name="cabinet",
            name="telephone",
            field=models.CharField(
                blank=True, max_length=30, verbose_name="Téléphone du cabinet"
            ),
        ),
        migrations.AlterField(
            model_name="cabinet",
            name="ville",
            field=models.CharField(
                blank=True,
                help_text="Imprimée sur les documents : « Rabat, le 16 octobre 2026 ».",
                max_length=80,
                verbose_name="Ville",
            ),
        ),
        migrations.RunPython(papier_errmili, migrations.RunPython.noop),
    ]
