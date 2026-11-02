import django.db.models.deletion
from django.db import migrations, models

from apps.common.tenant import fill_missing_cabinet


def rattacher_patient(apps, schema_editor):
    fill_missing_cabinet(apps, "patients", "Patient", ())


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_cabinet_specialite_entete"),
        ("patients", "0006_couverture_medicale"),
    ]

    operations = [
        migrations.RunPython(rattacher_patient, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="patient",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="patients",
                to="accounts.cabinet",
            ),
        ),
    ]
