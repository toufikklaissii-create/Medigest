import io
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.utils import timezone
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject
from xhtml2pdf import pisa

# Gabarits dessinés en A4 ; un profil A5 réduit toute la page (coordonnées et polices) de 1/√2.
A5_SCALE = 0.7071
A4_SIZE = (595.28, 841.89)
A5_SIZE = (419.53, 595.28)
MM = 72 / 25.4


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


def render_pdf(template_name, context, background=None, page_format="A4", offset_mm=(0, 0)):
    """Render a Django template to PDF bytes via xhtml2pdf (pure Python, no native deps).

    `background` is an optional static path to a one-page PDF (e.g. the cabinet's
    printed letterhead) laid under every page of the rendered document.
    `page_format` "A5" scales the A4 layout down to an A5 page; `offset_mm` (x, y)
    shifts the content right / down to match a printer on pre-printed paper.
    """
    html_string = render_to_string(template_name, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=html_string, dest=buffer, link_callback=_link_callback)
    if result.err:
        raise RuntimeError(f"Échec de la génération PDF pour {template_name}")
    pdf_bytes = buffer.getvalue()
    if background:
        pdf_bytes = _apply_background(pdf_bytes, background)
    return fit_pages(pdf_bytes, page_format, offset_mm)


def fit_pages(pdf_bytes, page_format="A4", offset_mm=(0, 0)):
    """Met chaque page A4 au format demandé (A5 : réduction × 0,7071) puis applique le décalage."""
    dx, dy = (float(value or 0) * MM for value in offset_mm)
    if page_format != "A5" and not dx and not dy:
        return pdf_bytes
    width, height = A5_SIZE if page_format == "A5" else A4_SIZE
    writer = PdfWriter()
    for source in PdfReader(io.BytesIO(pdf_bytes)).pages:
        page = writer.add_page(source)
        if page_format == "A5":
            page.add_transformation(Transformation().scale(A5_SCALE, A5_SCALE))
        if dx or dy:
            # PDF : origine en bas à gauche, donc un décalage vers le bas est un y négatif.
            page.add_transformation(Transformation().translate(dx, -dy))
        box = RectangleObject([0, 0, width, height])
        page.mediabox = box
        page.cropbox = box
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


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
