import django.db.models.deletion
from django.db import migrations, models

from apps.common.tenant import fill_missing_cabinet


def rattacher_appointment(apps, schema_editor):
    fill_missing_cabinet(apps, "appointments", "Appointment", ('patient',))


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0007_cabinet_obligatoire"),
        ("accounts", "0013_cabinet_specialite_entete"),
        ("appointments", "0003_whatsapp_tracking"),
    ]

    operations = [
        migrations.RunPython(rattacher_appointment, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="appointment",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="appointments",
                to="accounts.cabinet",
            ),
        ),
    ]
