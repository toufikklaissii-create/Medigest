from django.conf import settings


def assets(request):
    """CSS compilé (cabinet, hors ligne) ou Tailwind CDN (développement) : voir base.html."""
    return {"tailwind_compiled": settings.TAILWIND_COMPILED}
