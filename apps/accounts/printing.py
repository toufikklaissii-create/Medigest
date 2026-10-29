"""Page de test d'un profil d'impression : repères de la zone de texte sur le papier pré-imprimé."""
import io

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.common.pdf import fit_pages

# Zones de static/pdf/ordonnance_modele.pdf, en pt depuis le haut de la page A4
# (mêmes valeurs que templates/pdf/_print_base.html).
BODY_ZONE = {"left": 62, "top": 214, "width": 471, "height": 500}
DATE_ZONE = {"left": 284, "top": 178, "width": 170, "height": 28}
DATE_BASELINE = 195  # ligne d'écriture de la date dans DATE_ZONE
MARK = 14  # longueur des branches des repères (pt)

SAMPLE_LINES = [
    "Ligne d'exemple 1 : le texte doit tomber dans la zone blanche.",
    "Ligne d'exemple 2 : vérifiez les marges gauche et droite.",
    "Ligne d'exemple 3 : ajustez le décalage X / Y si besoin.",
]


def build_test_page(profile, date_label="16 octobre 2026"):
    """PDF sans fond, au format du profil et avec son décalage."""
    buffer = io.BytesIO()
    width, height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Page de test — {profile.get_document_type_display()}")
    pdf.setLineWidth(0.4)

    def y(top):
        return height - top

    # Repères en équerre aux 4 coins de la zone de texte.
    left, top = BODY_ZONE["left"], BODY_ZONE["top"]
    right, bottom = left + BODY_ZONE["width"], top + BODY_ZONE["height"]
    for cx, cy, sx, sy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
        pdf.line(cx, y(cy), cx + sx * MARK, y(cy))
        pdf.line(cx, y(cy), cx, y(cy + sy * MARK))

    # Croix au début de la ligne de date, puis la date telle qu'elle sera imprimée.
    cx, cy = DATE_ZONE["left"], DATE_BASELINE
    pdf.line(cx - 6, y(cy), cx + 6, y(cy))
    pdf.line(cx, y(cy - 6), cx, y(cy + 6))
    pdf.setFont("Times-Roman", 12)
    pdf.drawString(cx + 9, y(cy), date_label)

    pdf.setFont("Times-Roman", 11.5)
    for index, line in enumerate(SAMPLE_LINES):
        pdf.drawString(left, y(top + 24 + index * 18), line)

    pdf.setFont("Times-Italic", 8.5)
    pdf.drawString(
        left, y(bottom - 6),
        f"{profile.get_document_type_display()} · {profile.format} · décalage X {profile.decalage_x_mm} mm, "
        f"Y {profile.decalage_y_mm} mm · imprimer en taille réelle (100 %)",
    )
    pdf.showPage()
    pdf.save()
    return fit_pages(buffer.getvalue(), profile.format, (profile.decalage_x_mm, profile.decalage_y_mm))
