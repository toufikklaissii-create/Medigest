"""Documents patientes : validation par signature, enregistrement, lien signé « envoi depuis le téléphone »."""
from datetime import date

import qrcode
import qrcode.image.svg
from django.core import signing
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Consultation, PatientDocument

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PHONE_LINK_MAX_AGE = 15 * 60
PHONE_LINK_SALT = "medigest.patient-documents.phone-upload"

# Marques ISO-BMFF des photos HEIC/HEIF (iPhone, Android récents).
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}


def sniff_content_type(head):
    """Type réel d'après les premiers octets du fichier — jamais d'après l'extension."""
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[4:8] == b"ftyp" and head[8:12] in HEIC_BRANDS:
        return "image/heic"
    return None


def validate_upload(uploaded):
    """Retourne le type de contenu réel ou lève ValidationError (message en français)."""
    name = uploaded.name or "Fichier"
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"« {name} » dépasse 15 Mo : compressez-le ou scannez-le en plus basse résolution.")
    if uploaded.size == 0:
        raise ValidationError(f"« {name} » est vide.")
    uploaded.seek(0)
    head = uploaded.read(32)
    uploaded.seek(0)
    content_type = sniff_content_type(head)
    if content_type is None:
        raise ValidationError(f"« {name} » n'est pas accepté : seuls les PDF, JPG, PNG et HEIC sont autorisés.")
    return content_type


def parse_exam_date(value):
    try:
        parsed = date.fromisoformat(value) if value else None
    except ValueError:
        parsed = None
    return parsed


def save_documents(files, *, cabinet, patient, document_type, exam_date=None, consultation=None,
                   uploaded_by=None, title=""):
    """Valide puis enregistre chaque fichier. Retourne (documents créés, messages d'erreur).

    Un fichier refusé n'empêche pas l'enregistrement des autres.
    """
    if document_type not in PatientDocument.DocumentType.values:
        document_type = PatientDocument.DocumentType.AUTRE
    if consultation is not None and (consultation.patient_id != patient.pk or consultation.cabinet_id != cabinet.pk):
        consultation = None
    created, errors = [], []
    for uploaded in files:
        try:
            content_type = validate_upload(uploaded)
        except ValidationError as error:
            errors.append(error.messages[0])
            continue
        original_name = (uploaded.name or "document")[:255]
        doc_title = title if title and len(files) == 1 else original_name.rsplit(".", 1)[0]
        created.append(PatientDocument.objects.create(
            cabinet=cabinet,
            patient=patient,
            consultation=consultation,
            title=doc_title[:150] or "Document",
            document_type=document_type,
            exam_date=exam_date,
            file=uploaded,
            original_name=original_name,
            content_type=content_type,
            uploaded_by=uploaded_by,
        ))
    if not files:
        errors.append("Veuillez sélectionner au moins un fichier.")
    return created, errors


def consultation_for(cabinet, patient, consultation_id):
    if not consultation_id:
        return None
    return Consultation.objects.filter(pk=consultation_id, cabinet=cabinet, patient=patient).first()


def make_phone_token(patient, user):
    """Lien signé : une patiente, upload uniquement, valable PHONE_LINK_MAX_AGE secondes."""
    return signing.TimestampSigner(salt=PHONE_LINK_SALT).sign_object(
        {"p": patient.pk, "c": patient.cabinet_id, "u": user.pk}
    )


def read_phone_token(token):
    """Retourne le contenu du lien ou lève signing.SignatureExpired / signing.BadSignature."""
    return signing.TimestampSigner(salt=PHONE_LINK_SALT).unsign_object(token, max_age=PHONE_LINK_MAX_AGE)


def qr_svg(data):
    """QR code en SVG inline, généré localement (aucun service externe)."""
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    svg = image.to_string(encoding="unicode")
    return svg[svg.index("<svg"):] if "<svg" in svg else svg


def documents_context(request, patient):
    """Contexte du panneau « Documents » (partagé : dossier médecin et page assistante)."""
    cabinet = request.user.profile.cabinet
    consultations = (
        Consultation.objects.filter(cabinet=cabinet, patient=patient)
        .select_related("appointment")
        .order_by("-appointment__date")
    )
    return {
        "patient": patient,
        "documents": PatientDocument.objects.filter(cabinet=cabinet, patient=patient),
        "document_type_choices": PatientDocument.DocumentType.choices,
        "document_consultations": consultations,
        # L'assistante voit la liste mais n'ouvre jamais un document (contenu clinique).
        "can_open_documents": request.user.profile.role == "doctor",
        "today": timezone.localdate(),
    }
