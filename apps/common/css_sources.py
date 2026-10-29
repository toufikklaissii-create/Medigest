"""Empreinte des sources du CSS compilé (static/vendor/medigest.css).

Le CSS du cabinet est compilé à partir des templates et du thème Tailwind. Son en-tête porte
l'empreinte de ces sources : si un template change sans recompilation, le test
tests/test_offline_assets.py échoue et rappelle de lancer deploy\\construire_css.ps1.
"""
import hashlib
from pathlib import Path

HEADER_PREFIX = "/* medigest-sources: "
CSS_PATH = Path("static") / "vendor" / "medigest.css"
SOURCE_GLOBS = ("templates/**/*.html", "static/js/**/*.js", "tailwind.config.js")


def sources_digest(base_dir):
    base_dir = Path(base_dir)
    digest = hashlib.sha256()
    files = sorted({p for pattern in SOURCE_GLOBS for p in base_dir.glob(pattern) if p.is_file()})
    for path in files:
        digest.update(path.relative_to(base_dir).as_posix().encode())
        # Fins de ligne normalisées : même empreinte sous Windows (CRLF) et Linux (LF).
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def stamped_digest(base_dir):
    """Empreinte inscrite dans l'en-tête du CSS compilé, ou None."""
    css = Path(base_dir) / CSS_PATH
    if not css.exists():
        return None
    first_line = css.read_text(encoding="utf-8").split("\n", 1)[0]
    if not first_line.startswith(HEADER_PREFIX):
        return None
    return first_line[len(HEADER_PREFIX):].split(" ", 1)[0]


def stamp(base_dir):
    css = Path(base_dir) / CSS_PATH
    content = css.read_text(encoding="utf-8")
    if content.startswith(HEADER_PREFIX):
        content = content.split("\n", 1)[1]
    css.write_text(f"{HEADER_PREFIX}{sources_digest(base_dir)} */\n{content}", encoding="utf-8")
