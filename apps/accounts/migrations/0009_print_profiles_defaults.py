from django.db import migrations

DOCUMENT_TYPES = ["ordonnance", "compte_rendu", "lettre", "facture", "recu"]


def create_default_profiles(apps, schema_editor):
    """Les 5 profils d'impression de chaque cabinet existant : A4, décalage 0."""
    Cabinet = apps.get_model("accounts", "Cabinet")
    PrintProfile = apps.get_model("accounts", "PrintProfile")
    for cabinet in Cabinet.objects.all():
        for document_type in DOCUMENT_TYPES:
            PrintProfile.objects.get_or_create(
                cabinet=cabinet, document_type=document_type,
                defaults={"format": "A4", "decalage_x_mm": 0, "decalage_y_mm": 0, "actif": True},
            )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_print_profile"),
    ]

    operations = [
        migrations.RunPython(create_default_profiles, migrations.RunPython.noop),
    ]
