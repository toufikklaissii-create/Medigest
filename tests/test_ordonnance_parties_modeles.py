"""Ordonnance en 3 parties (médicaments, bilan biologique, radiologie) et modèles par symptomatologie."""
import io
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.models import Consultation, Document, ModeleOrdonnance
from apps.clinical.modeles_ordonnance_defaut import MODELES_DEFAUT, creer_modeles_defaut
from apps.patients.models import Patient


def pdf_text(content):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class OrdonnanceBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-ordonnance")
        self.other = Cabinet.objects.create(nom="Autre cabinet", slug="autre-cabinet")
        self.doctor = User.objects.create_user(username="dr_rx", password="x")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_rx", password="x")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        self.doc = Client()
        self.doc.force_login(self.doctor)
        self.ast = Client()
        self.ast.force_login(self.assistant)

        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Test", last_name="Patiente")
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(), status=Appointment.Status.IN_CONSULTATION
        )

    def autosave(self, **fields):
        return self.doc.post(reverse("clinical:autosave_consultation", args=[self.appt.pk]), fields)


class TroisPartiesTest(OrdonnanceBase):
    def test_autosave_enregistre_les_trois_parties(self):
        response = self.autosave(
            prescription_content="Acide folique 0,4 mg", bilan_content="NFS\nCRP", radiologie_content="Échographie pelvienne"
        )
        self.assertEqual(response.status_code, 204)
        docs = dict(Consultation.objects.get(appointment=self.appt).documents.values_list("document_type", "content"))
        self.assertEqual(docs[Document.DocumentType.PRESCRIPTION], "Acide folique 0,4 mg")
        self.assertEqual(docs[Document.DocumentType.BILAN_BIOLOGIQUE], "NFS\nCRP")
        self.assertEqual(docs[Document.DocumentType.RADIOLOGIE], "Échographie pelvienne")

    def test_une_partie_videe_est_effacee_et_les_absentes_conservees(self):
        self.autosave(prescription_content="Fer", bilan_content="NFS")
        self.autosave(prescription_content="Fer", bilan_content="")
        self.autosave(prescription_content="Fer 2")  # bilan absent du POST : inchangé
        docs = dict(Consultation.objects.get(appointment=self.appt).documents.values_list("document_type", "content"))
        self.assertEqual(docs[Document.DocumentType.BILAN_BIOLOGIQUE], "")
        self.assertEqual(docs[Document.DocumentType.PRESCRIPTION], "Fer 2")

    def test_trois_pdf_numerotes_avec_sous_titre(self):
        self.autosave(prescription_content="Acide folique", bilan_content="NFS\nCRP", radiologie_content="Échographie")
        medicaments = pdf_text(self.doc.get(reverse("clinical:prescription_pdf", args=[self.appt.pk])).content)
        self.assertIn("Acide folique", medicaments)
        self.assertNotIn("NFS", medicaments)
        self.assertNotIn("Bilan biologique", medicaments)

        bilan_response = self.doc.get(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "bilan"]))
        self.assertEqual(bilan_response["Content-Type"], "application/pdf")
        bilan = pdf_text(bilan_response.content)
        self.assertIn("Bilan biologique", bilan)
        self.assertIn("1-", bilan)
        self.assertIn("2-", bilan)
        self.assertLess(bilan.index("NFS"), bilan.index("CRP"))

        radio = pdf_text(self.doc.get(
            reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "radiologie"]) + "?mode=impression"
        ).content)
        self.assertIn("Examens radiologiques", radio)
        self.assertIn("Échographie", radio)

    def test_partie_inconnue_404(self):
        self.autosave(prescription_content="Fer")
        response = self.doc.get(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "inconnue"]))
        self.assertEqual(response.status_code, 404)

    def test_assistante_ne_peut_pas_imprimer_les_ordonnances(self):
        self.autosave(prescription_content="Fer", bilan_content="NFS")
        for part in ("bilan", "radiologie"):
            response = self.ast.get(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, part]))
            self.assertEqual(response.status_code, 403)

    def test_fiche_consultation_affiche_les_trois_parties(self):
        self.autosave(prescription_content="Fer", bilan_content="NFS-unique", radiologie_content="Radio-unique")
        html = self.doc.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        for name in ("prescription_content", "bilan_content", "radiologie_content"):
            self.assertIn(f'name="{name}"', html)
        self.assertIn("NFS-unique", html)
        self.assertIn(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "bilan"]), html)

    def test_dossier_patiente_affiche_bilan_et_radiologie(self):
        self.autosave(prescription_content="Fer", bilan_content="NFS-dossier")
        html = self.doc.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn("NFS-dossier", html)
        self.assertIn(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "bilan"]), html)
        self.assertNotIn(reverse("clinical:prescription_part_pdf", args=[self.appt.pk, "radiologie"]), html)


class ModelesOrdonnanceTest(OrdonnanceBase):
    def post(self, name, *args, **data):
        return self.doc.post(reverse(f"clinical:{name}", args=args), data)

    def test_modeles_de_depart_crees_une_seule_fois(self):
        self.assertEqual(creer_modeles_defaut(self.cabinet, ModeleOrdonnance), len(MODELES_DEFAUT))
        ModeleOrdonnance.objects.filter(cabinet=self.cabinet).first().delete()
        self.assertEqual(creer_modeles_defaut(self.cabinet, ModeleOrdonnance), 0)  # un modèle supprimé ne revient pas
        preconception = ModeleOrdonnance.objects.filter(nom="Bilan préconceptionnel").first()
        if preconception:
            self.assertIn("NFS", preconception.bilan_biologique)
            self.assertIn("Acide folique", preconception.medicaments)

    def test_ajouter_modifier_dupliquer_supprimer(self):
        response = self.post("modele_add", nom="Mycose vaginale", medicaments="Ovules", bilan_biologique="", radiologie="", actif="on")
        self.assertEqual(response.status_code, 200)
        self.assertIn("modele-added", response.headers["HX-Trigger"])
        modele = ModeleOrdonnance.objects.get(cabinet=self.cabinet, nom="Mycose vaginale")

        response = self.post("modele_card", modele.pk, nom="Mycose vaginale", medicaments="Ovules\nCrème",
                             bilan_biologique="Prélèvement vaginal", radiologie="", actif="on")
        self.assertEqual(response.status_code, 200)
        modele.refresh_from_db()
        self.assertEqual(modele.bilan_biologique, "Prélèvement vaginal")

        self.post("modele_duplicate", modele.pk)
        self.assertTrue(ModeleOrdonnance.objects.filter(nom="Mycose vaginale (copie)").exists())

        self.post("modele_delete", modele.pk)
        self.assertFalse(ModeleOrdonnance.objects.filter(pk=modele.pk).exists())

    def test_validation_nom_obligatoire_unique_et_contenu(self):
        ModeleOrdonnance.objects.create(cabinet=self.cabinet, nom="Grossesse", medicaments="Fer")
        response = self.post("modele_add", nom="", medicaments="Fer")
        self.assertContains(response, "Indiquez la symptomatologie")
        response = self.post("modele_add", nom="grossesse", medicaments="Fer")
        self.assertContains(response, "Un modèle porte déjà ce nom")
        response = self.post("modele_add", nom="Vide", medicaments="", bilan_biologique=" ", radiologie="")
        self.assertContains(response, "Remplissez au moins une partie")
        self.assertEqual(ModeleOrdonnance.objects.filter(cabinet=self.cabinet).count(), 1)

    def test_assistante_refusee_partout(self):
        modele = ModeleOrdonnance.objects.create(cabinet=self.cabinet, nom="Secret", medicaments="Fer")
        urls = [
            ("get", reverse("clinical:modeles_ordonnance")),
            ("post", reverse("clinical:modele_add")),
            ("get", reverse("clinical:modele_card", args=[modele.pk])),
            ("post", reverse("clinical:modele_card", args=[modele.pk])),
            ("post", reverse("clinical:modele_duplicate", args=[modele.pk])),
            ("post", reverse("clinical:modele_delete", args=[modele.pk])),
        ]
        for method, url in urls:
            response = getattr(self.ast, method)(url, {"nom": "x", "medicaments": "y"})
            self.assertEqual(response.status_code, 403, url)
        self.assertTrue(ModeleOrdonnance.objects.filter(pk=modele.pk, nom="Secret").exists())

    def test_modele_d_un_autre_cabinet_introuvable(self):
        autre = ModeleOrdonnance.objects.create(cabinet=self.other, nom="Autre", medicaments="Fer")
        self.assertEqual(self.doc.get(reverse("clinical:modele_card", args=[autre.pk])).status_code, 404)
        self.assertEqual(self.post("modele_delete", autre.pk).status_code, 404)
        self.assertTrue(ModeleOrdonnance.objects.filter(pk=autre.pk).exists())

    def test_consultation_propose_seulement_les_modeles_actifs_du_cabinet(self):
        ModeleOrdonnance.objects.create(cabinet=self.cabinet, nom="Actif-visible", medicaments="Fer")
        ModeleOrdonnance.objects.create(cabinet=self.cabinet, nom="Masque-invisible", medicaments="Fer", actif=False)
        ModeleOrdonnance.objects.create(cabinet=self.other, nom="Autre-invisible", medicaments="Fer")
        html = self.doc.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        self.assertIn("Actif-visible", html)
        self.assertNotIn("Masque-invisible", html)
        self.assertNotIn("Autre-invisible", html)

    def test_page_des_modeles(self):
        ModeleOrdonnance.objects.create(cabinet=self.cabinet, nom="Infection urinaire", medicaments="1- Fosfomycine")
        response = self.doc.get(reverse("clinical:modeles_ordonnance"))
        self.assertContains(response, "Infection urinaire")
        self.assertContains(response, "Fosfomycine")
        self.assertNotContains(response, "1- 1-")
