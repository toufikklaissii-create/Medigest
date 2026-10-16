import importlib
import io
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.accounts.branding import SAUGE_SCALE, brand_scale, contrast_with_white, css_variables
from apps.accounts.models import Cabinet, Profile

SAUGE_500_CHANNELS = "--brand-500: 82 121 111;"


class BrandScaleTest(SimpleTestCase):
    def test_default_color_keeps_exact_sauge_palette(self):
        self.assertEqual(brand_scale("#52796F"), SAUGE_SCALE)
        self.assertEqual(brand_scale("pas-une-couleur"), SAUGE_SCALE)
        self.assertIn(SAUGE_500_CHANNELS, css_variables())

    def test_light_pink_gets_readable_primary_buttons(self):
        for color in ("#F65387", "#F7A1C4", "#FFC0CB"):
            scale = brand_scale(color)
            self.assertEqual(scale[500], color.upper())
            self.assertGreaterEqual(contrast_with_white(scale[600]), 4.5, color)
            self.assertGreater(contrast_with_white(scale[700]), contrast_with_white(scale[600]), color)
            self.assertLess(contrast_with_white(scale[25]), 1.1, color)  # fond quasi blanc

    def test_dominant_color_of_cabinet_logo_is_pink(self):
        migration = importlib.import_module("apps.accounts.migrations.0004_cabinet_errmili_branding")
        color = migration.dominant_color(Path(settings.BASE_DIR) / "static" / "images" / "logo-cabinet.jpg")
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, 200)
        self.assertGreater(r - g, 80)  # rose : rouge nettement dominant
        self.assertGreater(b, g)


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    # Le stockage « manifest » de WhiteNoise exige collectstatic : stockage simple pour les tests.
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class CabinetBrandingPagesTest(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)

        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (246, 83, 135)).save(buffer, format="PNG")
        self.cabinet = Cabinet.objects.create(
            nom="Cabinet Rose", slug="cabinet-rose", couleur_primaire="#F65387",
            logo=SimpleUploadedFile("logo.png", buffer.getvalue(), content_type="image/png"),
        )
        self.user = User.objects.create_user(username="assist_rose", password="testpass123")
        Profile.objects.update_or_create(user=self.user, defaults={"role": Profile.Role.ASSISTANT, "cabinet": self.cabinet})

    def test_cabinet_login_page_uses_logo_and_cabinet_colors(self):
        html = Client().get(reverse("tenant_login", kwargs={"slug": "cabinet-rose"})).content.decode()
        self.assertIn(self.cabinet.logo.url, html)
        self.assertIn("--brand-500: 246 83 135;", html)
        self.assertIn("from-sauge-700", html)

    def test_discovery_page_keeps_medigest_palette(self):
        html = Client().get(reverse("accounts:login")).content.decode()
        self.assertIn(SAUGE_500_CHANNELS, html)

    def test_logged_in_pages_switch_palette_and_show_sidebar_logo(self):
        client = Client()
        client.login(username="assist_rose", password="testpass123")
        html = client.get(reverse("appointments:assistant_dashboard")).content.decode()
        self.assertIn("--brand-500: 246 83 135;", html)
        self.assertIn(f'<img src="{self.cabinet.logo.url}" alt="Logo Cabinet Rose"', html)
        self.assertNotIn(SAUGE_500_CHANNELS, html)
