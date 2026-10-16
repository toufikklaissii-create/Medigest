"""Branding du cabinet Dr ERRMILI : logo copié dans media + couleur dominante extraite du logo."""

import colorsys
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import migrations

CABINET_SLUG = "cabinet-dr-errmili"
LOGO_SOURCE = Path(settings.BASE_DIR) / "static" / "images" / "logo-cabinet.jpg"


def dominant_color(path):
    """Couleur dominante saturée (blancs, gris et quasi-noirs ignorés), au format #RRGGBB."""
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((240, 240))
        pixels = list(image.getdata())

    buckets = Counter()
    members = {}
    for r, g, b in pixels:
        _, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if lightness > 0.9 or lightness < 0.12 or saturation < 0.35:
            continue  # fond blanc, anti-crénelage gris, ombres
        key = (r // 24, g // 24, b // 24)
        buckets[key] += 1
        members.setdefault(key, []).append((r, g, b))
    if not buckets:
        return None
    best = members[buckets.most_common(1)[0][0]]
    return "#" + "".join(f"{round(sum(c[i] for c in best) / len(best)):02X}" for i in range(3))


def apply_branding(apps, schema_editor):
    Cabinet = apps.get_model("accounts", "Cabinet")
    cabinet = Cabinet.objects.filter(slug=CABINET_SLUG).first()
    if cabinet is None or not LOGO_SOURCE.exists():
        return

    color = dominant_color(LOGO_SOURCE)
    if color:
        cabinet.couleur_primaire = color
    if not cabinet.logo:
        with LOGO_SOURCE.open("rb") as handle:
            cabinet.logo.save("logo-cabinet.jpg", File(handle), save=False)
    cabinet.save(update_fields=["couleur_primaire", "logo"])
    print(f"\n  Branding {CABINET_SLUG} : couleur primaire extraite du logo = {color}, logo = {cabinet.logo.name}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_cabinet_branding"),
    ]

    operations = [
        migrations.RunPython(apply_branding, migrations.RunPython.noop),
    ]
