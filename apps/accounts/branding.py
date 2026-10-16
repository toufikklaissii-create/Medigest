"""Thème par cabinet : échelle de couleurs « brand » 25→950 dérivée de Cabinet.couleur_primaire.

La couleur primaire du cabinet sert de pas 500. Les pas clairs sont éclaircis et les pas
foncés assombris en HSL. Le pas 600 (boutons primaires, texte blanc) est assombri si besoin
jusqu'à un contraste WCAG AA (4,5:1) avec le blanc.
"""

import colorsys
from functools import lru_cache

DEFAULT_PRIMARY = "#52796F"

# Palette sauge d'origine (DESIGN.md §1.1), conservée à l'identique pour la couleur par défaut.
SAUGE_SCALE = {
    25: "#F8FAF9",
    50: "#F4F7F5",
    100: "#E3ECE7",
    200: "#C9D8D0",
    400: "#6B9080",
    500: "#52796F",
    600: "#354F52",
    700: "#2E4345",
    900: "#2F3E46",
    950: "#25333A",
}

STEPS = (25, 50, 100, 200, 400, 500, 600, 700, 900, 950)
# Pas clairs : part de blanc mélangée en luminosité ; pas foncés : facteur appliqué à la luminosité.
LIGHTEN = {25: 0.965, 50: 0.93, 100: 0.84, 200: 0.68, 400: 0.28}
DARKEN = {600: 0.80, 700: 0.66}
# Sidebar (900 → 950) : prune très foncé, désaturé et légèrement décalé vers le violet.
DEEP = {900: (0.42, 0.21, 0.58), 950: (0.30, 0.15, 0.55)}  # pas: (facteur, luminosité max, facteur de saturation)
DEEP_HUE_SHIFT = -12 / 360
AA_TEXT = 4.5


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{round(c):02X}" for c in rgb)


def _relative_luminance(rgb):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_with_white(hex_color):
    return 1.05 / (_relative_luminance(_hex_to_rgb(hex_color)) + 0.05)


def _from_hls(h, l, s):
    return _rgb_to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))))


def is_valid_hex(value):
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


@lru_cache(maxsize=64)
def brand_scale(primary=DEFAULT_PRIMARY):
    """Échelle {pas: '#RRGGBB'} ; la couleur par défaut renvoie la palette sauge exacte."""
    if not is_valid_hex(primary) or primary.upper() == DEFAULT_PRIMARY.upper():
        return dict(SAUGE_SCALE)

    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in _hex_to_rgb(primary)))
    scale = {500: primary.upper()}
    for step, mix in LIGHTEN.items():
        # Les fonds très clairs restent teintés mais désaturés, pour ne pas « crier ».
        scale[step] = _from_hls(h, l + (1 - l) * mix, s * (0.85 if step <= 100 else 0.95))
    for step, factor in DARKEN.items():
        scale[step] = _from_hls(h, l * factor, s)
    for step, (factor, max_lightness, sat_factor) in DEEP.items():
        scale[step] = _from_hls((h + DEEP_HUE_SHIFT) % 1, min(l * factor, max_lightness), s * sat_factor)

    # Boutons primaires : texte blanc lisible (AA) sur brand-600, sinon on assombrit.
    l600 = l * DARKEN[600]
    while contrast_with_white(scale[600]) < AA_TEXT and l600 > 0.05:
        l600 -= 0.01
        scale[600] = _from_hls(h, l600, s)
    l700 = min(l * DARKEN[700], l600 - 0.06)
    scale[700] = _from_hls(h, l700, s)
    return {step: scale[step] for step in STEPS}


def css_variables(primary=DEFAULT_PRIMARY):
    """Déclarations CSS « --brand-500: 82 121 111; … » (canaux RGB pour <alpha-value> Tailwind)."""
    return " ".join(
        f"--brand-{step}: {' '.join(str(c) for c in _hex_to_rgb(color))};"
        for step, color in brand_scale(primary).items()
    )
