from apps.common.pdf import render_pdf, save_pdf_copy


def generate_receipt_pdf(invoice, save_copy=True):
    patient = invoice.patient
    pdf_bytes = render_pdf(
        "pdf/receipt.html",
        {
            "patient": patient,
            "doc_date": invoice.paid_at or invoice.created_at,
            "invoice": invoice,
            "items": invoice.items.select_related("act"),
        },
    )
    if save_copy:
        save_pdf_copy(patient, "recu", pdf_bytes, reference=invoice.invoice_number)
    return pdf_bytes
