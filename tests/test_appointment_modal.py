"""La fenêtre « Nouveau rendez-vous » ne doit se fermer qu'après la création du RDV.

Régression constatée au cabinet : la recherche de patiente et la création express envoient leurs
propres requêtes depuis l'intérieur du formulaire ; un `htmx:after-request` non filtré fermait la
fenêtre avant que l'assistante puisse valider, et aucun RDV n'était créé.
"""
from pathlib import Path

from django.conf import settings


def test_modal_closes_only_on_its_own_post():
    html = (Path(settings.BASE_DIR) / "templates" / "assistant" / "_appointment_modal_content.html").read_text(
        encoding="utf-8"
    )
    handler = next(line for line in html.splitlines() if "@htmx:after-request" in line)
    assert "requestConfig.path === $el.getAttribute('hx-post')" in handler
