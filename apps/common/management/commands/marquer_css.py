from django.conf import settings
from django.core.management.base import BaseCommand

from apps.common.css_sources import sources_digest, stamp


class Command(BaseCommand):
    help = "Inscrit l'empreinte des templates dans static/vendor/medigest.css (après compilation Tailwind)."

    def handle(self, *args, **options):
        stamp(settings.BASE_DIR)
        self.stdout.write(self.style.SUCCESS(f"CSS marqué : {sources_digest(settings.BASE_DIR)[:12]}"))
