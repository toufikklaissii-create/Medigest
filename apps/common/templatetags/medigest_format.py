from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def duree_courte(value, now=None):
    """Durée écoulée au format court : « 12 min », « 1 h 05 ». Remplace |timesince."""
    if not value:
        return ""
    minutes = int(((now or timezone.now()) - value).total_seconds() // 60)
    if minutes < 1:
        return "moins d'1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d}"


@register.filter
def dh(value):
    """Montant au format « 1 250,00 DH » : espace insécable (U+00A0) pour les milliers et avant DH."""
    if value in (None, ""):
        return ""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " DH"
