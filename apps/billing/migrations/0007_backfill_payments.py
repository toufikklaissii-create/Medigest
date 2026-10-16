from django.db import migrations


def backfill_payments(apps, schema_editor):
    """Une facture déjà payée devient un Payment unique, daté de son paid_at (recette au jour d'encaissement)."""
    Invoice = apps.get_model("billing", "Invoice")
    Payment = apps.get_model("billing", "Payment")
    paid = Invoice.objects.filter(status="paid", total_amount__gt=0, payments__isnull=True)
    Payment.objects.bulk_create(
        Payment(
            invoice=invoice,
            amount=invoice.total_amount,
            method=invoice.payment_method or "cash",
            paid_at=invoice.paid_at or invoice.created_at,
        )
        for invoice in paid
    )


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0006_payments_discount_cancellation"),
    ]

    operations = [
        migrations.RunPython(backfill_payments, migrations.RunPython.noop),
    ]
