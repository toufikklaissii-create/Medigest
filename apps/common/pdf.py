import io
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from xhtml2pdf import pisa


def render_pdf(template_name, context):
    """Render a Django template to PDF bytes via xhtml2pdf (pure Python, no native deps)."""
    html_string = render_to_string(template_name, context)
    buffer = io.BytesIO()
    result = pisa.CreatePDF(src=html_string, dest=buffer)
    if result.err:
        raise RuntimeError(f"Échec de la génération PDF pour {template_name}")
    return buffer.getvalue()


def save_pdf_copy(patient, document_kind, pdf_bytes, reference=""):
    """Archive a generated PDF under media/documents/<patient_number>/<date>/.

    Returns the path written, relative to MEDIA_ROOT.
    """
    today = timezone.localdate().isoformat()
    directory = Path(settings.MEDIA_ROOT) / "documents" / patient.patient_number / today
    directory.mkdir(parents=True, exist_ok=True)

    suffix = f"_{reference}" if reference else ""
    timestamp = timezone.now().strftime("%H%M%S")
    filename = f"{document_kind}{suffix}_{timestamp}.pdf"
    file_path = directory / filename
    file_path.write_bytes(pdf_bytes)
    return file_path.relative_to(settings.MEDIA_ROOT)
