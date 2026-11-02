"""Papier à en-tête des PDF « avec en-tête », propre à chaque cabinet.

- Le cabinet a chargé son papier (Réglages) : on l'utilise tel quel.
- Sinon : en-tête sobre généré à partir du nom du cabinet, du médecin, de la spécialité,
  de l'adresse et des mentions légales. Il respecte les mêmes zones que le papier du
  cabinet Errmili (texte entre 146 et 714 pt depuis le haut), donc les gabarits ne changent pas.
"""
import io

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.accounts.printing import DATE_BASELINE, DATE_ZONE

DEFAULT_COLOR = "#6B9080"


def pdf_colors(cabinet):
    """Couleurs des PDF (filets, titres, tableaux) dérivées de la couleur du cabinet."""
    from apps.accounts.branding import brand_scale

    scale = brand_scale(getattr(cabinet, "couleur_primaire", "") or DEFAULT_COLOR)
    return {"line": scale[200], "title": scale[600], "border": scale[100], "head_bg": scale[25], "head_text": scale[900]}


def letterhead_for(cabinet, ordonnance=False):
    """Fond à poser sous le document : chemin du PDF chargé, ou PDF généré (bytes)."""
    if cabinet is not None:
        uploaded = (cabinet.entete_ordonnance_pdf or cabinet.entete_pdf) if ordonnance else cabinet.entete_pdf
        if uploaded:
            try:
                return uploaded.path
            except (NotImplementedError, ValueError):
                pass
    return generated_letterhead(cabinet, ordonnance=ordonnance)


def _titular_doctor_name(cabinet):
    from apps.accounts.models import Profile

    profile = (
        Profile.objects.filter(cabinet=cabinet, role=Profile.Role.DOCTOR, user__is_active=True)
        .select_related("user").order_by("pk").first()
    )
    if profile is None:
        return ""
    name = profile.user.get_full_name().strip() or profile.user.username
    return name if name.lower().startswith("dr") else f"Dr {name}"


def generated_letterhead(cabinet, ordonnance=False):
    width, height = A4
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    color = HexColor(getattr(cabinet, "couleur_primaire", "") or DEFAULT_COLOR)
    left, right = 62, width - 62

    def y(top):
        return height - top

    if cabinet is not None:
        pdf.setFillColor(color)
        pdf.setFont("Times-Bold", 17)
        pdf.drawString(left, y(64), cabinet.nom[:60])
        pdf.setFillColor(HexColor("#111827"))
        lines = [part for part in (_titular_doctor_name(cabinet), cabinet.get_specialite_display()) if part]
        pdf.setFont("Times-Roman", 12)
        pdf.drawString(left, y(84), " — ".join(lines)[:90])
        contact = [part for part in (cabinet.adresse, cabinet.ville, cabinet.telephone and f"Tél. {cabinet.telephone}") if part]
        if contact:
            pdf.setFont("Times-Roman", 10)
            pdf.setFillColor(HexColor("#4B5563"))
            pdf.drawString(left, y(102), " · ".join(contact)[:110])
        pdf.setStrokeColor(color)
        pdf.setLineWidth(1.2)
        pdf.line(left, y(122), right, y(122))

        legal = [f"{label} {value}" for label, value in (
            ("INPE", cabinet.inpe), ("IF", cabinet.identifiant_fiscal), ("ICE", cabinet.ice), ("Patente", cabinet.patente),
        ) if value]
        pdf.setLineWidth(0.6)
        pdf.line(left, y(770), right, y(770))
        if legal:
            pdf.setFont("Times-Roman", 8.5)
            pdf.setFillColor(HexColor("#4B5563"))
            pdf.drawCentredString(width / 2, y(784), "  ·  ".join(legal))

    if ordonnance:
        # Le gabarit d'ordonnance n'imprime que la date : le titre et « Ville, le » sont sur le papier.
        pdf.setFillColor(HexColor("#111827"))
        pdf.setFont("Times-Bold", 16)
        pdf.drawCentredString(width / 2, y(156), "ORDONNANCE")
        pdf.setFont("Times-Roman", 12)
        ville = getattr(cabinet, "ville", "") or ""
        # Même ligne que la date écrite par le gabarit dans DATE_ZONE (elle tombe ~6 pt au-dessus de la ligne d'écriture).
        pdf.drawRightString(DATE_ZONE["left"] - 4, y(DATE_BASELINE - 6), f"{ville}, le" if ville else "Le")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
