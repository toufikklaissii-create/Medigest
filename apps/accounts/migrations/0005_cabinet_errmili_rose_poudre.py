"""Cabinet Dr ERRMILI : rose poudré #B84A6E à la place du rose vif extrait du logo (#F65387)."""

from django.db import migrations

CABINET_SLUG = "cabinet-dr-errmili"


def set_rose_poudre(apps, schema_editor):
    apps.get_model("accounts", "Cabinet").objects.filter(slug=CABINET_SLUG).update(couleur_primaire="#B84A6E")


def restore_logo_color(apps, schema_editor):
    apps.get_model("accounts", "Cabinet").objects.filter(slug=CABINET_SLUG).update(couleur_primaire="#F65387")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_cabinet_errmili_branding"),
    ]

    operations = [
        migrations.RunPython(set_rose_poudre, restore_logo_color),
    ]
