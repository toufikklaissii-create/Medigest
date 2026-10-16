import io
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from xhtml2pdf import pisa


def _link_callback(uri, rel):
    """Resolve /static/… and /media/… URIs (images, fonts) to local files for xhtml2pdf.

    Anything else is refused, so a template can never make the PDF engine read
    an arbitrary path or fetch a remote URL.
    """
    path = uri.lstrip("/")
    static_prefix = settings.STATIC_URL.lstrip("/")
    media_prefix = settings.MEDIA_URL.lstrip("/")
    if path.startswith(static_prefix):
        resolved = finders.find(path[len(static_prefix):])
        if resolved:
            return resolved
    elif path.startswith(media_prefix):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        candidate = (media_root / path[len(media_prefix):]).resolve()
        if candidate.is_relative_to(media_root) and candidate.is_file():
            return str(candidate)
    raise ValueError(f"Ressource PDF introuvable ou non autorisée : {uri}")


def render_pdf(template_name, context, background=None):
    """Render a Django template to PDF bytes via xhtml2pdf (pure Python, no native deps).

    `background` is an optional static path to a one-page PDF (e.g. the cabinet's
    printed letterhead) laid under every page of the rendered document.
    """
    html_string = render_to_string(template_name, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=html_string, dest=buffer, link_callback=_link_callback)
    if result.err:
        raise RuntimeError(f"Échec de la génération PDF pour {template_name}")
    if background:
        return _apply_background(buffer.getvalue(), background)
    return buffer.getvalue()


def _apply_background(pdf_bytes, background):
    """Merge each page of `pdf_bytes` over the first page of the static PDF `background`.

    Done with pypdf directly rather than xhtml2pdf's @page background-image, which
    goes through temporary files that Windows cannot reopen.
    """
    background_path = finders.find(background)
    if not background_path:
        raise RuntimeError(f"Fond PDF introuvable : {background}")
    background_page = PdfReader(background_path).pages[0]

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
        writer.add_page(page).merge_page(background_page, over=False)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def save_pdf_copy(patient, document_kind, pdf_bytes, reference=""):
    """Archive a generated PDF under media/documents/<cabinet_id>/<patient_number>/<date>/.

    Returns the path written, relative to MEDIA_ROOT.
    """
    today = timezone.localdate().isoformat()
    directory = Path(settings.MEDIA_ROOT) / "documents" / str(patient.cabinet_id or 0) / patient.patient_number / today
    directory.mkdir(parents=True, exist_ok=True)

    suffix = f"_{reference}" if reference else ""
    timestamp = timezone.now().strftime("%H%M%S")
    filename = f"{document_kind}{suffix}_{timestamp}.pdf"
    file_path = directory / filename
    file_path.write_bytes(pdf_bytes)
    return file_path.relative_to(settings.MEDIA_ROOT)
