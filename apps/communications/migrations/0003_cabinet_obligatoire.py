import django.db.models.deletion
from django.db import migrations, models

from apps.common.tenant import fill_missing_cabinet


def rattacher_task(apps, schema_editor):
    fill_missing_cabinet(apps, "communications", "Task", ('patient',))


class Migration(migrations.Migration):

    dependencies = [
        ("patients", "0007_cabinet_obligatoire"),
        ("accounts", "0013_cabinet_specialite_entete"),
        ("communications", "0002_task_cabinet"),
    ]

    operations = [
        migrations.RunPython(rattacher_task, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="task",
            name="cabinet",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tasks",
                to="accounts.cabinet",
            ),
        ),
    ]
