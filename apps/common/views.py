"""Service protégé de MEDIA_ROOT : /media/ n'est plus jamais servi en accès libre (DEBUG ou non)."""
import posixpath

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, HttpResponseForbidden
from django.views.static import serve

from apps.clinical.models import PatientDocument
from apps.patients.models import Patient

# Seuls les logos de cabinet sont publics (page de connexion, avant authentification).
PUBLIC_PREFIXES = ("cabinets/logos/",)


def _is_allowed(cabinet, path):
    parts = path.split("/")
    if parts[0] == "patient_documents":
        return PatientDocument.objects.filter(cabinet=cabinet, file=path).exists()
    if parts[0] == "documents" and len(parts) >= 3:
        # PDF générés : documents/<cabinet_id>/<N° dossier>/… ou ancien format documents/<N° dossier>/…
        if parts[1].isdigit():
            return (
                len(parts) >= 4
                and cabinet is not None
                and int(parts[1]) == cabinet.pk
                and Patient.objects.filter(cabinet=cabinet, patient_number=parts[2]).exists()
            )
        return Patient.objects.filter(cabinet=cabinet, patient_number=parts[1]).exists()
    return False


def media_file(request, path):
    path = posixpath.normpath(path).lstrip("/")
    if path == "." or path.startswith("..") or "/../" in f"/{path}/":
        raise Http404
    if path.startswith(PUBLIC_PREFIXES):
        return serve(request, path, document_root=settings.MEDIA_ROOT)

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    profile = getattr(request.user, "profile", None)
    if profile is None or profile.role != "doctor":
        return HttpResponseForbidden("Accès refusé : documents réservés au médecin.")
    if not _is_allowed(profile.cabinet, path):
        raise Http404

    response = serve(request, path, document_root=settings.MEDIA_ROOT)
    response["Cache-Control"] = "private, no-store"
    return response
