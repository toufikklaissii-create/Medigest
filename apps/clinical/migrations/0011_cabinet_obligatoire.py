import django.db.models.deletion
from django.db import migrations, models

from apps.common.tenant import fill_missing_cabinet


def rattacher_consultation(apps, schema_editor):
    fill_missing_cabinet(apps, "clinical", "Consultation", ('appointment', 'patient'))


def rattacher_patientdocument(apps, schema_editor):
    fill_missing_cabinet(apps, "clinical", "PatientDocument", ('patient',))


class Migration(migrations.Migration):

    dependencies = [
        ("appointments", "0004_cabinet_obligatoire"),
        ("patients", "0007_cabinet_obligatoire"),
        ("accounts", "0013_cabinet_specialite_entete"),
        ("clinical", "0010_modeles_courrier"),
    ]

    operations = [
        migrations.RunPython(rattacher_consultation, migrations.RunPython.noop),
        migrations.RunPython(rattacher_patientdocument, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="consultation",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="consultations",
                to="accounts.cabinet",
            ),
        ),
        migrations.AlterField(
            model_name="patientdocument",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="patient_documents",
                to="accounts.cabinet",
            ),
        ),
    ]
