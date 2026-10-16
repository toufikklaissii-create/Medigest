from .branding import DEFAULT_PRIMARY, css_variables
from .models import Cabinet


def _current_cabinet(request):
    """Cabinet de l'utilisateur connecté, sinon celui de la page de connexion /c/<slug>/login/."""
    user = getattr(request, "user", None)
    profile = getattr(user, "profile", None) if user is not None and user.is_authenticated else None
    if profile is not None and profile.cabinet_id:
        return profile.cabinet
    match = getattr(request, "resolver_match", None)
    if match is not None and match.url_name == "tenant_login":
        return Cabinet.objects.filter(slug=match.kwargs.get("slug"), actif=True).first()
    return None


def brand(request):
    """Variables CSS --brand-25 … --brand-950 (palette sauge par défaut) + cabinet pour le logo."""
    cabinet = _current_cabinet(request)
    primary = cabinet.couleur_primaire if cabinet else DEFAULT_PRIMARY
    return {"brand_cabinet": cabinet, "brand_css_vars": css_variables(primary)}
