import django.db.models.deletion
from django.db import migrations, models

from apps.common.tenant import fill_missing_cabinet


def rattacher_invoice(apps, schema_editor):
    fill_missing_cabinet(apps, "billing", "Invoice", ('patient',))


def rattacher_medicalact(apps, schema_editor):
    fill_missing_cabinet(apps, "billing", "MedicalAct", ())


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0007_cabinet_obligatoire"),
        ("accounts", "0013_cabinet_specialite_entete"),
        ("billing", "0010_tarifs_prix_libre"),
    ]

    operations = [
        migrations.RunPython(rattacher_invoice, migrations.RunPython.noop),
        migrations.RunPython(rattacher_medicalact, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="invoice",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="invoices",
                to="accounts.cabinet",
            ),
        ),
        migrations.AlterField(
            model_name="medicalact",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="medical_acts",
                to="accounts.cabinet",
            ),
        ),
    ]
