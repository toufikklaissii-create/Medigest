"""Ordonnance : lignes numérotées « 1- », « 2- »… sans doubler un numéro déjà tapé."""
import io
from datetime import date
from types import SimpleNamespace

from pypdf import PdfReader

from apps.clinical.services import prescription_lines
from apps.common.pdf import render_pdf


def test_existing_numbers_and_bullets_are_removed():
    content = "1- Acide folique\n2. Calcium\n3) Fer\n- Repos\n• Hydratation\n\n  Échographie 3D  "
    assert prescription_lines(content) == ["Acide folique", "Calcium", "Fer", "Repos", "Hydratation", "Échographie 3D"]


def test_dosage_numbers_are_kept():
    assert prescription_lines("Acide folique 0,4 mg\n500 mg paracétamol") == [
        "Acide folique 0,4 mg", "500 mg paracétamol",
    ]


def test_printed_prescription_is_numbered():
    context = {
        "doc_date": date(2026, 10, 17),
        "patient": SimpleNamespace(first_name="Test", last_name="Patiente", age=34),
        "prescription_lines": prescription_lines("Acide folique 0,4 mg\nCalcium"),
    }
    pdf = render_pdf("pdf/prescription.html", context, page_format="A5")
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "1-" in text and "2-" in text
    assert text.index("Acide folique") < text.index("Calcium")


def test_a5_text_is_enlarged_but_a4_unchanged():
    from django.template.loader import render_to_string

    base = {"doc_date": date(2026, 10, 17), "patient": SimpleNamespace(first_name="T", last_name="P", age=30),
            "prescription_lines": ["Fer"]}
    assert "font-size: 16pt" in render_to_string("pdf/prescription.html", {**base, "a5": True})
    assert "font-size: 16pt" not in render_to_string("pdf/prescription.html", {**base, "a5": False})
    for template in ("pdf/_print_base.html", "pdf/_letterhead_base.html"):
        assert "font-size: 15pt" in render_to_string(template, {**base, "a5": True})


def test_short_a5_prescription_fits_on_one_page():
    """Régression cabinet : en A5 (texte agrandi) la date débordait de sa case et tout passait page 2."""
    for subtitle in ("", "Bilan biologique"):
        context = {
            "a5": True, "subtitle": subtitle,
            "doc_date": date(2026, 9, 17),  # « 17 septembre 2026 » : le mois le plus long
            "patient": SimpleNamespace(first_name="Samira", last_name="Testlongnom", age=34),
            "prescription_lines": prescription_lines("nocand 200 mg cp 1cp prise unique\ndermofix creme\nc gel TV"),
        }
        pdf = render_pdf("pdf/prescription.html", context, page_format="A5", offset_mm=(0, 14))
        reader = PdfReader(io.BytesIO(pdf))
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        assert "17 septembre 2026" in text and "1-" in text and "c gel TV" in text
