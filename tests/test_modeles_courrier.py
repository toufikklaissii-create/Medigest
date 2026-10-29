"""Certificats et courriers : 6 types, modèles par la doctoresse, champs remplis automatiquement."""
import io
import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.courriers import (
    COURRIER_TYPES, MODELES_COURRIER_DEFAUT, creer_modeles_courrier_defaut, remplir, valeurs_champs,
)
from apps.clinical.models import Consultation, Document, ModeleCourrier
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
class CourrierBase(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-courrier", ville="Khemisset")
        self.other = Cabinet.objects.create(nom="Autre", slug="autre-courrier")
        self.doctor = User.objects.create_user(username="dr_c", password="x", first_name="Khadija", last_name="Errmili")
        Profile.objects.update_or_create(user=self.doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": self.cabinet})
        self.assistant = User.objects.create_user(username="as_c", password="x")
        Profile.objects.update_or_create(
            user=self.assistant, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet}
        )
        self.doc = Client()
        self.doc.force_login(self.doctor)
        self.ast = Client()
        self.ast.force_login(self.assistant)

        self.patient = Patient.objects.create(
            cabinet=self.cabinet, first_name="Samira", last_name="Test", cin="AB123456",
            birth_date=date(1992, 3, 12),
        )
        self.appt = Appointment.objects.create(
            cabinet=self.cabinet, patient=self.patient, date=timezone.now(), status=Appointment.Status.IN_CONSULTATION,
        )
        self.consultation = Consultation.objects.create(
            appointment=self.appt, patient=self.patient, doctor=self.doctor, cabinet=self.cabinet,
            last_menstrual_period=timezone.localdate() - timedelta(days=12 * 7 + 3),
        )


class ChampsTest(CourrierBase):
    def test_champs_remplis(self):
        valeurs = valeurs_champs(self.patient, self.consultation, doctor_name="Dr Khadija Errmili", ville="Khemisset")
        texte = remplir("{patiente}, {age}, née le {date_naissance}, CIN {cin}, {terme}, DPA {dpa}, {docteur}, {ville}", valeurs)
        self.assertIn("Mme Samira Test", texte)
        self.assertIn("12 SA + 3 j", texte)
        self.assertIn("CIN AB123456", texte)
        self.assertIn("12 mars 1992", texte)
        self.assertIn("Dr Khadija Errmili", texte)
        self.assertNotIn("{", texte)

    def test_champs_inconnus_entre_crochets_et_accolades_libres_conservees(self):
        patient = Patient.objects.create(cabinet=self.cabinet, first_name="A", last_name="B")
        valeurs = valeurs_champs(patient, None)
        self.assertEqual(remplir("{ddr} / {terme} / {age} / {autre}", valeurs), "[DDR] / [terme] / [âge] / {autre}")


class ModelesDepartTest(CourrierBase):
    def test_un_modele_au_moins_par_type_et_creation_unique(self):
        types = {m["type_document"] for m in MODELES_COURRIER_DEFAUT}
        self.assertEqual(types, {t["key"] for t in COURRIER_TYPES})
        self.assertEqual(creer_modeles_courrier_defaut(self.cabinet, ModeleCourrier), len(MODELES_COURRIER_DEFAUT))
        ModeleCourrier.objects.filter(cabinet=self.cabinet).first().delete()
        self.assertEqual(creer_modeles_courrier_defaut(self.cabinet, ModeleCourrier), 0)

    def test_aucun_modele_de_depart_n_est_vide(self):
        for data in MODELES_COURRIER_DEFAUT:
            self.assertTrue(data["contenu"].strip(), data["nom"])


class GestionModelesTest(CourrierBase):
    def post(self, name, *args, **data):
        return self.doc.post(reverse(f"clinical:{name}", args=args), data)

    def test_page_liste_par_type(self):
        creer_modeles_courrier_defaut(self.cabinet, ModeleCourrier)
        response = self.doc.get(reverse("clinical:modeles_courrier"))
        for courrier in COURRIER_TYPES:
            self.assertContains(response, f'id="courriers-{courrier["key"]}"')
        self.assertContains(response, "Certificat prénuptial")
        self.assertContains(response, "{patiente}")

    def test_ajouter_modifier_dupliquer_supprimer(self):
        response = self.post("courrier_add", type_document="arret_travail", nom="Arrêt 3 jours",
                             contenu="{patiente} : arrêt de 3 jours.", actif="on")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["HX-Retarget"], "#courriers-arret_travail")
        modele = ModeleCourrier.objects.get(cabinet=self.cabinet, nom="Arrêt 3 jours")

        self.post("courrier_card", modele.pk, type_document="arret_travail", nom="Arrêt 3 jours",
                  contenu="{patiente} : arrêt de 3 jours ouvrables.", actif="on")
        modele.refresh_from_db()
        self.assertIn("ouvrables", modele.contenu)

        response = self.post("courrier_card", modele.pk, type_document="certificate", nom="Arrêt 3 jours",
                             contenu="Texte", actif="on")
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.post("courrier_duplicate", modele.pk)
        self.assertTrue(ModeleCourrier.objects.filter(nom="Arrêt 3 jours (copie)").exists())
        self.post("courrier_delete", modele.pk)
        self.assertFalse(ModeleCourrier.objects.filter(pk=modele.pk).exists())

    def test_validation(self):
        ModeleCourrier.objects.create(cabinet=self.cabinet, type_document="letter", nom="Avis", contenu="x")
        self.assertContains(self.post("courrier_add", type_document="inconnu", nom="X", contenu="y"), "Choisissez le type")
        self.assertContains(self.post("courrier_add", type_document="letter", nom="avis", contenu="y"), "porte déjà ce nom")
        self.assertContains(self.post("courrier_add", type_document="letter", nom="Vide", contenu="  "), "Écrivez le texte")
        # Même nom autorisé dans un autre type.
        self.post("courrier_add", type_document="certificate", nom="Avis", contenu="y")
        self.assertEqual(ModeleCourrier.objects.filter(cabinet=self.cabinet, nom="Avis").count(), 2)

    def test_assistante_refusee(self):
        modele = ModeleCourrier.objects.create(cabinet=self.cabinet, type_document="letter", nom="Secret", contenu="x")
        for method, url in (
            ("get", reverse("clinical:modeles_courrier")),
            ("post", reverse("clinical:courrier_add")),
            ("get", reverse("clinical:courrier_card", args=[modele.pk])),
            ("post", reverse("clinical:courrier_duplicate", args=[modele.pk])),
            ("post", reverse("clinical:courrier_delete", args=[modele.pk])),
        ):
            self.assertEqual(getattr(self.ast, method)(url, {"nom": "x"}).status_code, 403, url)
        self.assertTrue(ModeleCourrier.objects.filter(pk=modele.pk).exists())

    def test_modele_d_un_autre_cabinet_introuvable(self):
        autre = ModeleCourrier.objects.create(cabinet=self.other, type_document="letter", nom="Autre", contenu="x")
        self.assertEqual(self.doc.get(reverse("clinical:courrier_card", args=[autre.pk])).status_code, 404)


class ConsultationCourrierTest(CourrierBase):
    def test_modeles_proposes_remplis_pour_la_patiente(self):
        ModeleCourrier.objects.create(cabinet=self.cabinet, type_document="cert_grossesse", nom="Décla",
                                      contenu="{patiente} est enceinte de {terme}.")
        ModeleCourrier.objects.create(cabinet=self.cabinet, type_document="letter", nom="Masqué-invisible",
                                      contenu="x", actif=False)
        html = self.doc.get(reverse("clinical:consultation_detail", args=[self.appt.pk])).content.decode()
        self.assertIn("Mme Samira Test est enceinte de 12 SA + 3 j.", html)
        self.assertNotIn("Masqué-invisible", html)
        for courrier in COURRIER_TYPES:
            self.assertIn(f'name="courrier_{courrier["key"]}"', html)

    def test_autosave_enregistre_tous_les_courriers(self):
        response = self.doc.post(reverse("clinical:autosave_consultation", args=[self.appt.pk]), {
            "courrier_certificate": "Certificat X", "courrier_arret_travail": "Arrêt 5 jours",
            "courrier_letter": "", "courrier_hospitalisation": "Demande Y",
        })
        self.assertEqual(response.status_code, 204)
        docs = dict(self.consultation.documents.values_list("document_type", "content"))
        self.assertEqual(docs["certificate"], "Certificat X")
        self.assertEqual(docs["arret_travail"], "Arrêt 5 jours")
        self.assertEqual(docs["hospitalisation"], "Demande Y")
        self.assertNotIn("letter", docs)

    def test_chaque_type_s_imprime_avec_son_titre(self):
        for courrier in COURRIER_TYPES:
            Document.objects.update_or_create(consultation=self.consultation, document_type=courrier["key"],
                                              defaults={"content": f"Texte {courrier['key']}"})
            response = self.doc.get(reverse("clinical:letter_pdf", args=[self.appt.pk, courrier["key"]]))
            self.assertEqual(response.status_code, 200, courrier["key"])
            text = pdf_text(response.content)
            self.assertIn(courrier["title"].upper(), text)
            self.assertIn(f"Texte {courrier['key']}", text)

    def test_dossier_patiente_liste_les_courriers_rediges(self):
        Document.objects.create(consultation=self.consultation, document_type="arret_travail", content="Arrêt")
        html = self.doc.get(reverse("clinical:patient_file", args=[self.patient.pk])).content.decode()
        self.assertIn(reverse("clinical:letter_pdf", args=[self.appt.pk, "arret_travail"]), html)
        self.assertNotIn(reverse("clinical:letter_pdf", args=[self.appt.pk, "hospitalisation"]), html)


class ImpressionCourrierTest(CourrierBase):
    def test_retours_a_la_ligne_et_titre_en_mode_impression(self):
        """Régression cabinet (xhtml2pdf 0.2.17) : les retours à la ligne disparaissaient à l'impression."""
        Document.objects.create(consultation=self.consultation, document_type="cert_grossesse",
                                content="Ligne une.\n\nTerme : 12 SA\nDPA : plus tard")
        url = reverse("clinical:letter_pdf", args=[self.appt.pk, "cert_grossesse"])
        text = pdf_text(self.doc.get(url, {"mode": "impression"}).content)
        self.assertIn("CERTIFICAT DE GROSSESSE", text)
        lines = [line.strip() for line in text.splitlines()]
        self.assertIn("Ligne une.", lines)
        self.assertIn("Terme : 12 SA", lines)
        self.assertIn("DPA : plus tard", lines)
