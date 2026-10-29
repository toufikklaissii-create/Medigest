"""Au cabinet, l'application fonctionne sans internet : aucune ressource externe dans les pages."""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Cabinet, Profile

EXTERNAL = re.compile(r"""(?:src|href)=["']https?://""")
STATIC_STORAGE = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=STATIC_STORAGE)
class OfflineAssetsTest(TestCase):
    def setUp(self):
        cabinet = Cabinet.objects.create(nom="Cabinet Test", slug="cabinet-offline")
        doctor = User.objects.create_user(username="dr_off", password="x")
        Profile.objects.update_or_create(user=doctor, defaults={"role": Profile.Role.DOCTOR, "cabinet": cabinet})
        self.client = Client()
        self.client.force_login(doctor)

    def html(self):
        response = self.client.get(reverse("appointments:assistant_dashboard"), follow=True)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    @override_settings(TAILWIND_COMPILED=True)
    def test_cabinet_pages_load_nothing_from_internet(self):
        html = self.html()
        self.assertEqual(EXTERNAL.findall(html), [])
        self.assertIn("vendor/medigest.css", html)
        self.assertNotIn("cdn.tailwindcss.com", html)

    @override_settings(TAILWIND_COMPILED=False)
    def test_development_keeps_tailwind_cdn_with_shared_theme(self):
        html = self.html()
        self.assertIn("cdn.tailwindcss.com", html)
        self.assertIn("js/tailwind-theme.js", html)
        self.assertNotIn("vendor/medigest.css", html)

    def test_vendored_files_exist(self):
        static = Path(settings.BASE_DIR) / "static"
        html = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(encoding="utf-8")
        for name in re.findall(r"\{% static '([^']+)' %\}", html):
            self.assertTrue((static / name).is_file(), name)
        fonts_css = (static / "vendor" / "fonts" / "plus-jakarta-sans.css").read_text(encoding="utf-8")
        for font in re.findall(r"url\(([^)]+)\)", fonts_css):
            self.assertTrue((static / "vendor" / "fonts" / font).is_file(), font)


class CompiledCssUpToDateTest(TestCase):
    def test_compiled_css_matches_templates(self):
        from apps.common.css_sources import sources_digest, stamped_digest

        self.assertEqual(
            stamped_digest(settings.BASE_DIR), sources_digest(settings.BASE_DIR),
            "Templates ou thème modifiés sans recompiler le CSS du cabinet : "
            "lancer deploy\\construire_css.ps1 puis relancer les tests.",
        )
