import json
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Cabinet, Profile
from apps.appointments.models import Appointment
from apps.clinical.documents import MAX_UPLOAD_BYTES, make_phone_token, sniff_content_type
from apps.clinical.models import Consultation, PatientDocument
from apps.patients.models import Patient

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32


@override_settings(ALLOWED_HOSTS=["testserver"], DEBUG=False)
class PatientDocumentsTest(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        media_override = self.settings(MEDIA_ROOT=media)
        media_override.enable()
        self.addCleanup(media_override.disable)
        self.media_root = media

        self.cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-docs")
        self.doctor = self._user("dr_docs", Profile.Role.DOCTOR, self.cabinet)
        self.assistant = self._user("assist_docs", Profile.Role.ASSISTANT, self.cabinet)
        self.patient = Patient.objects.create(cabinet=self.cabinet, first_name="Salma", last_name="Bennani")

        self.other_cabinet = Cabinet.objects.create(nom="Autre cabinet", slug="autre-docs")
        self.other_doctor = self._user("dr_other", Profile.Role.DOCTOR, self.other_cabinet)

        self.doctor_client = self._client("dr_docs")
        self.assistant_client = self._client("assist_docs")
        self.upload_url = reverse("patients:patient_documents", args=[self.patient.pk])

    def _user(self, username, role, cabinet):
        user = User.objects.create_user(username=username, password="testpass123")
        Profile.objects.update_or_create(user=user, defaults={"role": role, "cabinet": cabinet})
        return user

    def _client(self, username):
        client = Client()
        client.login(username=username, password="testpass123")
        return client

    def _upload(self, client=None, **extra):
        data = {"document_type": "radio", "exam_date": "2026-10-01",
                "files": [SimpleUploadedFile("radio bassin.pdf", PDF, content_type="application/pdf")]}
        data.update(extra)
        return (client or self.doctor_client).post(self.upload_url, data)

    def _document(self):
        self._upload()
        return PatientDocument.objects.get(patient=self.patient)

    # --- Stockage & modèle -------------------------------------------------------------

    def test_upload_stores_random_name_per_patient_and_keeps_original(self):
        document = self._document()
        self.assertEqual(document.original_name, "radio bassin.pdf")
        self.assertTrue(document.file.name.startswith(f"patient_documents/{self.cabinet.pk}/{self.patient.pk}/"))
        self.assertNotIn("radio", document.file.name)
        self.assertEqual(document.content_type, "application/pdf")
        self.assertEqual(document.document_type, PatientDocument.DocumentType.RADIO)
        self.assertEqual(str(document.exam_date), "2026-10-01")
        self.assertEqual(document.uploaded_by, self.doctor)

    def test_multiple_files_and_optional_consultation(self):
        appt = Appointment.objects.create(cabinet=self.cabinet, patient=self.patient, date=timezone.now())
        consultation = Consultation.objects.create(appointment=appt, patient=self.patient, cabinet=self.cabinet, doctor=self.doctor)
        response = self.doctor_client.post(
            self.upload_url,
            {"consultation": consultation.pk, "document_type": "echographie", "exam_date": "2026-10-02",
             "files": [SimpleUploadedFile("a.png", PNG), SimpleUploadedFile("b.jpg", JPG), SimpleUploadedFile("c.heic", HEIC)]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.headers["HX-Trigger"])["documents-changed"]["count"], 3)
        docs = PatientDocument.objects.filter(patient=self.patient)
        self.assertEqual(docs.count(), 3)
        self.assertEqual({d.content_type for d in docs}, {"image/png", "image/jpeg", "image/heic"})
        self.assertTrue(all(d.consultation_id == consultation.pk for d in docs))

    def test_documents_ordered_by_exam_date(self):
        self._upload(exam_date="2026-01-10")
        self._upload(exam_date="2026-09-10")
        self._upload(exam_date="2026-05-10")
        dates = [str(d.exam_date) for d in PatientDocument.objects.filter(patient=self.patient)]
        self.assertEqual(dates, ["2026-09-10", "2026-05-10", "2026-01-10"])

    # --- Validation ----------------------------------------------------------------------

    def test_sniffing_uses_signature_not_extension(self):
        self.assertEqual(sniff_content_type(PDF), "application/pdf")
        self.assertEqual(sniff_content_type(HEIC), "image/heic")
        self.assertIsNone(sniff_content_type(b"MZ\x90\x00 exe"))

    def test_disguised_file_is_rejected_with_french_message(self):
        response = self.doctor_client.post(
            self.upload_url,
            {"document_type": "bilan", "files": [SimpleUploadedFile("bilan.pdf", b"MZ\x90\x00 not a pdf")]},
            HTTP_HX_REQUEST="true",
        )
        self.assertFalse(PatientDocument.objects.exists())
        toast = json.loads(response.headers["HX-Trigger"])["toast"]
        self.assertEqual(toast["type"], "error")
        self.assertIn("seuls les PDF, JPG, PNG et HEIC sont autorisés", toast["message"])

    def test_file_over_15_mb_is_rejected(self):
        big = SimpleUploadedFile("scan.pdf", PDF + b"0" * MAX_UPLOAD_BYTES)
        response = self.doctor_client.post(self.upload_url, {"files": [big]}, HTTP_HX_REQUEST="true")
        self.assertFalse(PatientDocument.objects.exists())
        self.assertIn("15 Mo", json.loads(response.headers["HX-Trigger"])["toast"]["message"])

    def test_valid_files_saved_even_if_one_is_refused(self):
        self.doctor_client.post(self.upload_url, {"files": [
            SimpleUploadedFile("ok.pdf", PDF), SimpleUploadedFile("virus.png", b"<script>alert(1)</script>"),
        ]})
        self.assertEqual(PatientDocument.objects.count(), 1)

    # --- Accès protégé ---------------------------------------------------------------------

    def test_doctor_opens_document_inline(self):
        document = self._document()
        response = self.doctor_client.get(reverse("clinical:patient_document_file", args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), PDF)
        download = self.doctor_client.get(reverse("clinical:patient_document_file", args=[document.pk]) + "?download=1")
        self.assertIn("attachment", download["Content-Disposition"])

    def test_access_denied_without_login(self):
        document = self._document()
        anonymous = Client()
        protected = anonymous.get(reverse("clinical:patient_document_file", args=[document.pk]))
        self.assertEqual(protected.status_code, 302)
        self.assertIn("login", protected["Location"])
        raw = anonymous.get(f"/media/{document.file.name}")
        self.assertEqual(raw.status_code, 302)
        self.assertIn("login", raw["Location"])

    def test_other_cabinet_gets_404(self):
        document = self._document()
        other = self._client("dr_other")
        self.assertEqual(other.get(reverse("clinical:patient_document_file", args=[document.pk])).status_code, 404)
        self.assertEqual(other.get(f"/media/{document.file.name}").status_code, 404)

    def test_assistant_sees_list_but_cannot_open(self):
        document = self._document()
        page = self.assistant_client.get(self.upload_url)
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("radio bassin", html)
        self.assertIn("Réservé au médecin", html)
        self.assertNotIn(reverse("clinical:patient_document_file", args=[document.pk]), html)
        self.assertNotIn(document.file.name, html)
        self.assertEqual(self.assistant_client.get(reverse("clinical:patient_document_file", args=[document.pk])).status_code, 403)
        self.assertEqual(self.assistant_client.get(f"/media/{document.file.name}").status_code, 403)

    def test_media_served_with_debug_false_only_through_protected_view(self):
        document = self._document()
        self.assertEqual(self.doctor_client.get(f"/media/{document.file.name}").status_code, 200)
        self.assertEqual(self.doctor_client.get("/media/patient_documents/../../manage.py").status_code, 404)
        self.assertEqual(self.doctor_client.get("/media/inconnu/fichier.pdf").status_code, 404)

    def test_generated_pdf_copies_are_protected(self):
        from apps.common.pdf import save_pdf_copy
        relative = save_pdf_copy(self.patient, "ordonnance", PDF).as_posix()
        self.assertTrue(relative.startswith(f"documents/{self.cabinet.pk}/{self.patient.patient_number}/"))
        self.assertEqual(self.doctor_client.get(f"/media/{relative}").status_code, 200)
        self.assertEqual(Client().get(f"/media/{relative}").status_code, 302)
        self.assertEqual(self.assistant_client.get(f"/media/{relative}").status_code, 403)
        self.assertEqual(self._client("dr_other").get(f"/media/{relative}").status_code, 404)

    def test_cabinet_logo_stays_public(self):
        import os
        os.makedirs(os.path.join(self.media_root, "cabinets", "logos"))
        with open(os.path.join(self.media_root, "cabinets", "logos", "logo.png"), "wb") as fh:
            fh.write(PNG)
        self.assertEqual(Client().get("/media/cabinets/logos/logo.png").status_code, 200)

    # --- Envoi depuis le téléphone ----------------------------------------------------------

    def test_qr_panel_contains_signed_link(self):
        response = self.assistant_client.get(reverse("patients:phone_upload_qr", args=[self.patient.pk]))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("<svg", html)
        self.assertIn("/patients/envoi/", html)

    def test_qr_for_other_cabinet_patient_is_404(self):
        other = self._client("dr_other")
        self.assertEqual(other.get(reverse("patients:phone_upload_qr", args=[self.patient.pk])).status_code, 404)

    def test_mobile_upload_without_login(self):
        url = reverse("patients:phone_upload", args=[make_phone_token(self.patient, self.assistant)])
        phone = Client()
        page = phone.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'capture="environment"')
        self.assertContains(page, "Salma B.")
        self.assertNotContains(page, "Bennani")
        response = phone.post(url, {"document_type": "bilan", "files": [SimpleUploadedFile("IMG_0042.JPG", JPG)]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Document envoyé")
        document = PatientDocument.objects.get(patient=self.patient)
        self.assertEqual(document.cabinet, self.cabinet)
        self.assertEqual(document.document_type, "bilan")
        self.assertEqual(document.uploaded_by, self.assistant)
        self.assertEqual(document.exam_date, timezone.localdate())

    def test_mobile_link_rejects_disallowed_file(self):
        url = reverse("patients:phone_upload", args=[make_phone_token(self.patient, self.doctor)])
        response = Client().post(url, {"files": [SimpleUploadedFile("note.txt", b"bonjour")]})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "seuls les PDF, JPG, PNG et HEIC sont autorisés", status_code=400)
        self.assertFalse(PatientDocument.objects.exists())

    def test_expired_signed_link(self):
        token = make_phone_token(self.patient, self.doctor)
        url = reverse("patients:phone_upload", args=[token])
        later = timezone.now() + timedelta(minutes=16)
        with mock.patch("django.core.signing.time.time", return_value=later.timestamp()):
            page = Client().get(url)
            post = Client().post(url, {"files": [SimpleUploadedFile("a.pdf", PDF)]})
        self.assertEqual(page.status_code, 410)
        self.assertContains(page, "Ce lien a expiré", status_code=410)
        self.assertEqual(post.status_code, 410)
        self.assertFalse(PatientDocument.objects.exists())

    def test_tampered_link_is_refused(self):
        token = make_phone_token(self.patient, self.doctor)
        response = Client().get(reverse("patients:phone_upload", args=[token[:-2] + "xx"]))
        self.assertEqual(response.status_code, 404)

    def test_signed_link_is_upload_only(self):
        self._document()
        url = reverse("patients:phone_upload", args=[make_phone_token(self.patient, self.doctor)])
        html = Client().get(url).content.decode()
        self.assertNotIn("radio bassin", html)
        self.assertNotIn("patient_documents/", html)
