import re

from django.conf import settings
from django.http import HttpResponseForbidden


class ClinicalAccessMiddleware:
    """Unconditionally blocks the 'assistant' role from any clinical URL.

    This is a safety net independent of individual views' @role_required
    decorators: even a clinical view that forgets to decorate itself stays
    inaccessible to an assistant.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.prefixes = tuple(getattr(settings, "CLINICAL_URL_PREFIXES", ["/clinical/"]))

    def __call__(self, request):
        if request.path.startswith(self.prefixes):
            profile = getattr(getattr(request, "user", None), "profile", None)
            if profile is not None and profile.role == "assistant":
                return HttpResponseForbidden("Accès refusé : zone clinique réservée au médecin.")
        return self.get_response(request)


class MoneyAccessMiddleware:
    """Bloque le médecin remplaçant sur tout ce qui touche à l'argent (facturation, caisse,
    recettes, rapports, tarifs, accueil de l'assistante avec ses encaissements).

    Filet de sécurité indépendant des vues et des menus : même une URL tapée à la main est refusée.
    """

    MONEY_PATHS = re.compile(
        r"^/(billing/|appointments/$|appointments/reception/|appointments/\d+/advance/)"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        profile = getattr(getattr(request, "user", None), "profile", None)
        if profile is not None and profile.role == "remplacant" and self.MONEY_PATHS.match(request.path):
            return HttpResponseForbidden("Accès refusé : la facturation et la caisse ne sont pas accessibles au remplaçant.")
        return self.get_response(request)
