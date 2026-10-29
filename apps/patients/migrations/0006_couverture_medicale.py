
from django.db import migrations, models

from apps.patients.couverture import deviner_couverture


def classer_fiches_existantes(apps, schema_editor):
    """Range les fiches déjà saisies quand l'ancien texte libre est sans ambiguïté
    (« CNSS », « cnops », « aucune »…). Le texte d'origine est conservé tel quel ; les cas
    douteux restent « non renseignée » et apparaissent dans la liste « à vérifier »."""
    Patient = apps.get_model("patients", "Patient")
    for patient in Patient.objects.exclude(organisme_social="").filter(couverture="").only("pk", "organisme_social"):
        code = deviner_couverture(patient.organisme_social)
        if code:
            Patient.objects.filter(pk=patient.pk).update(couverture=code)


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0005_alter_patient_patient_number_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="patient",
            name="couverture",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cnops", "CNOPS"),
                    ("cnss", "CNSS"),
                    ("aucune", "Sans couverture"),
                    ("autre", "Autre (mutuelle, FAR, assurance…)"),
                ],
                help_text="Vide = non renseignée (à vérifier).",
                max_length=10,
                verbose_name="Couverture médicale",
            ),
        ),
        migrations.AlterField(
            model_name="patient",
            name="organisme_social",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="Précision (mutuelle, n° d'affiliation…)",
            ),
        ),
        migrations.RunPython(classer_fiches_existantes, migrations.RunPython.noop),
    ]
