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
