"""Isolement entre cabinets : aucune page ne laisse voir ni modifier les données d'un autre cabinet.

Le test parcourt AUTOMATIQUEMENT toutes les adresses de Medigest qui prennent un identifiant,
les appelle avec les identifiants du cabinet B en étant connecté au cabinet A (médecin,
assistante, remplaçant), puis vérifie :
- qu'aucune réponse ne contient une donnée du cabinet B (page, PDF ou Excel) ;
- qu'aucun POST n'a modifié une donnée du cabinet B.
Une nouvelle page ajoutée plus tard est donc testée sans rien écrire de plus.
"""
import io
import itertools
import zipfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.billing.models import Invoice, InvoiceItem, MedicalAct, Payment
from apps.clinical.models import Consultation, ConsultationAct, Document, ModeleCourrier, ModeleOrdonnance
from apps.communications.models import Task
from apps.patients.models import Patient

SECRET = "ZZSECRETB"
STR_VALUES = {
    "part": ["medicaments", "bilan", "radiologie"],
    "letter_type": ["certificate", "cert_grossesse"],
    "kind": ["certificat", "ordonnance"],
    "action": ["reminder", "confirm"],
    "document_type": ["ordonnance", "lettre"],
    "slug": ["cabinet-b"],
}
SKIP_PREFIXES = ("admin:",)
# Page de connexion publique d'un cabinet : son nom y est affiché par conception.
PUBLIC_NAMES = {"tenant_login"}


def iter_patterns(resolver=None, prefix=""):
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            namespace = f"{prefix}{pattern.namespace}:" if pattern.namespace else prefix
            yield from iter_patterns(pattern, namespace)
        elif isinstance(pattern, URLPattern) and pattern.name:
            yield f"{prefix}{pattern.name}", pattern.pattern.converters


def response_text(response):
    content = b"".join(response.streaming_content) if response.streaming else response.content
    kind = response.get("Content-Type", "")
    if "pdf" in kind:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    if "spreadsheet" in kind:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return "\n".join(archive.read(n).decode("utf-8", "ignore") for n in archive.namelist() if n.endswith(".xml"))
    return content.decode("utf-8", "ignore")


@override_settings(ALLOWED_HOSTS=["testserver"])
class CabinetIsolationTest(TestCase):
    def make_cabinet(self, slug, marker):
        cabinet = Cabinet.objects.create(nom=f"Cabinet {marker}", slug=slug)
        users = {}
        for role in (Profile.Role.DOCTOR, Profile.Role.ASSISTANT, Profile.Role.REMPLACANT):
            user = User.objects.create_user(username=f"{role}_{slug}", password="x", last_name=marker)
            Profile.objects.update_or_create(user=user, defaults={"role": role, "cabinet": cabinet})
            users[role] = user
        patient = Patient.objects.create(cabinet=cabinet, first_name=marker, last_name=marker,
                                         organisme_social=marker, medical_history=marker)
        act = MedicalAct.objects.create(cabinet=cabinet, code="CONS", name=f"Acte {marker}", price=Decimal("300"))
        old = Appointment.objects.create(cabinet=cabinet, patient=patient, reason=marker,
                                         date=timezone.now() - timedelta(days=5),
                                         status=Appointment.Status.COMPLETED)
        current = Appointment.objects.create(cabinet=cabinet, patient=patient, reason=marker, date=timezone.now(),
                                             status=Appointment.Status.WAITING)
        consultation = Consultation.objects.create(
            appointment=old, patient=patient, cabinet=cabinet, doctor=users[Profile.Role.DOCTOR],
            diagnostic=marker, clinical_notes=marker,
        )
        ConsultationAct.objects.create(consultation=consultation, act=act, price=act.price)
        Document.objects.create(consultation=consultation, document_type=Document.DocumentType.PRESCRIPTION, content=marker)
        Document.objects.create(consultation=consultation, document_type=Document.DocumentType.CERTIFICATE, content=marker)
        invoice = Invoice.objects.create(cabinet=cabinet, patient=patient, total_amount=Decimal("300"))
        InvoiceItem.objects.create(invoice=invoice, act=act, price=act.price)
        payment = Payment.objects.create(invoice=invoice, amount=Decimal("100"), method=Payment.Method.CASH,
                                         paid_at=timezone.now(), received_by=users[Profile.Role.ASSISTANT])
        Task.objects.create(cabinet=cabinet, author=users[Profile.Role.DOCTOR],
                            assignee=users[Profile.Role.ASSISTANT], title=marker, patient=patient)
        ModeleOrdonnance.objects.create(cabinet=cabinet, nom=marker, medicaments=marker)
        ModeleCourrier.objects.create(cabinet=cabinet, type_document="certificate", nom=marker, contenu=marker)
        return {"cabinet": cabinet, "users": users, "patient": patient, "consultation": consultation,
                "invoice": invoice, "payment": payment, "act": act, "current": current}

    def setUp(self):
        self.a = self.make_cabinet("cabinet-a", "AAAPUBLIC")
        self.b = self.make_cabinet("cabinet-b", SECRET)

    def ids_of_b(self):
        ids = set()
        for model in (Patient, Appointment, Consultation, Invoice, Payment, MedicalAct, Task, Document,
                      ModeleOrdonnance, ModeleCourrier, User):
            field = "profile__cabinet" if model is User else (
                "consultation__cabinet" if model is Document else
                "invoice__cabinet" if model is Payment else "cabinet")
            ids.update(model.objects.filter(**{field: self.b["cabinet"]}).values_list("pk", flat=True))
        return sorted(ids)

    def fingerprint_b(self):
        cabinet = self.b["cabinet"]
        return (
            list(Patient.objects.filter(cabinet=cabinet).values_list("pk", "first_name", "couverture", "medical_history")),
            list(Appointment.objects.filter(cabinet=cabinet).values_list("pk", "status", "date")),
            list(Consultation.objects.filter(cabinet=cabinet).values_list("pk", "status", "diagnostic")),
            list(Invoice.objects.filter(cabinet=cabinet).values_list("pk", "status", "total_amount")),
            list(Payment.objects.filter(invoice__cabinet=cabinet).values_list("pk", "amount")),
            list(MedicalAct.objects.filter(cabinet=cabinet).values_list("pk", "price", "is_active")),
            list(Task.objects.filter(cabinet=cabinet).values_list("pk", "status", "title")),
            list(ModeleOrdonnance.objects.filter(cabinet=cabinet).values_list("pk", "nom", "actif")),
            list(ModeleCourrier.objects.filter(cabinet=cabinet).values_list("pk", "nom", "actif")),
            list(Document.objects.filter(consultation__cabinet=cabinet).values_list("pk", "content")),
            list(User.objects.filter(profile__cabinet=cabinet).values_list("pk", "is_active", "password")),
        )

    def urls_with_ids(self):
        ids_b = self.ids_of_b()
        for name, converters in iter_patterns():
            if not converters or name.startswith(SKIP_PREFIXES) or name in PUBLIC_NAMES:
                continue
            choices = []
            for param, converter in converters.items():
                if type(converter).__name__ == "IntConverter":
                    choices.append([(param, value) for value in ids_b])
                else:
                    choices.append([(param, value) for value in STR_VALUES.get(param, ["x"])])
            for combo in itertools.product(*choices):
                try:
                    yield reverse(name, kwargs=dict(combo))
                except Exception:  # noqa: BLE001 — paramètre refusé par l'URL : rien à tester
                    continue

    def test_aucune_page_ne_montre_les_donnees_d_un_autre_cabinet(self):
        urls = list(self.urls_with_ids())
        self.assertGreater(len(urls), 50)
        leaks = []
        for role, user in self.a["users"].items():
            client = Client()
            client.force_login(user)
            for url in urls:
                response = client.get(url)
                if response.status_code == 200 and SECRET in response_text(response):
                    leaks.append(f"{role} GET {url}")
        self.assertEqual(leaks, [])

    def test_listes_et_recherches_restent_dans_le_cabinet(self):
        names = [
            "patients:index", "appointments:assistant_dashboard", "appointments:calendar", "appointments:patient_search",
            "appointments:patient_picker_search", "clinical:doctor_dashboard", "clinical:modeles_ordonnance",
            "clinical:modeles_courrier", "billing:index", "billing:reports", "billing:daily_revenue",
            "billing:cash_register", "billing:tariffs", "billing:export_xlsx", "billing:export_pdf",
            "billing:pending_invoices", "communications:index", "accounts:remplacants", "accounts:settings",
        ]
        leaks = []
        for role, user in self.a["users"].items():
            client = Client()
            client.force_login(user)
            for name in names:
                # Recherche sur un début de nom : la page peut répéter la saisie, jamais la fiche complète.
                for params in ({}, {"q": SECRET[:5]}, {"periode": "mois"}):
                    response = client.get(reverse(name), params)
                    if response.status_code == 200 and SECRET in response_text(response):
                        leaks.append(f"{role} {name} {params}")
        self.assertEqual(leaks, [])

    def test_aucun_post_ne_modifie_un_autre_cabinet(self):
        before = self.fingerprint_b()
        urls = list(self.urls_with_ids())
        payload = {"action": "validate", "status": "cancelled", "amount": "300", "method": "cash", "reason": "x",
                   "first_name": "Pirate", "last_name": "Pirate", "couverture": "cnss", "nom": "Pirate",
                   "medicaments": "Pirate", "contenu": "Pirate", "price": "1", "password": "Pirate-2026!",
                   "password2": "Pirate-2026!", "diagnostic": "Pirate", "title": "Pirate"}
        for user in self.a["users"].values():
            client = Client()
            client.force_login(user)
            for url in urls:
                client.post(url, payload)
        self.assertEqual(self.fingerprint_b(), before)

    def test_controle_positif_le_detecteur_voit_bien_les_donnees(self):
        """Garde-fou du test lui-même : le médecin de B voit bien ses propres données."""
        client = Client()
        client.force_login(self.b["users"][Profile.Role.DOCTOR])
        response = client.get(reverse("clinical:patient_file", args=[self.b["patient"].pk]))
        self.assertIn(SECRET, response_text(response))
        response = client.get(reverse("clinical:prescription_pdf", args=[self.b["consultation"].appointment_id]))
        self.assertIn(SECRET, response_text(response))
