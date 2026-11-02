"""Outils partagés des tests."""
from pathlib import Path

from django.conf import settings
from django.core.files import File

STATIC_PDF = Path(settings.BASE_DIR) / "static" / "pdf"


def attach_errmili_letterhead(cabinet):
    """Charge le papier du cabinet Errmili sur `cabinet` (comme depuis les Réglages)."""
    for field, filename in (("entete_pdf", "entete_cabinet.pdf"), ("entete_ordonnance_pdf", "ordonnance_modele.pdf")):
        with (STATIC_PDF / filename).open("rb") as handle:
            getattr(cabinet, field).save(f"{cabinet.slug}_{filename}", File(handle), save=False)
    cabinet.save()
