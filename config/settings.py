import os
import socket
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, True))
# Au cabinet, la configuration vit hors du code : C:\Medigest\medigest.env, à côté de C:\Medigest\app.
# Une mise à jour remplace le code sans toucher aux secrets ni aux chemins des données.
ENV_FILE = Path(os.environ.get("MEDIGEST_ENV_FILE", ""))
if not ENV_FILE.is_file():
    ENV_FILE = BASE_DIR.parent / "medigest.env"
if not ENV_FILE.is_file():
    ENV_FILE = BASE_DIR / ".env"
environ.Env.read_env(ENV_FILE)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-secret-key-change-me")
DEBUG = env.bool("DEBUG", default=True)
if not DEBUG and SECRET_KEY.startswith("dev-insecure"):
    raise RuntimeError("DJANGO_SECRET_KEY manquante : impossible de démarrer en production.")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# Cabinet (DEBUG=False) : CSS Tailwind compilé, aucune ressource chargée depuis internet.
# Développement : Tailwind CDN pour voir tout de suite les nouvelles classes.
TAILWIND_COMPILED = env.bool("TAILWIND_COMPILED", default=not DEBUG)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "apps.common",
    "apps.accounts",
    "apps.patients",
    "apps.appointments",
    "apps.clinical",
    "apps.billing",
    "apps.communications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.accounts.middleware.ClinicalAccessMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.communications.context_processors.active_task_count",
                "apps.accounts.context_processors.brand",
                "apps.common.context_processors.assets",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
    # SQLite ignores select_for_update(): IMMEDIATE makes every atomic() block take
    # the write lock up front, which is what serializes patient/invoice numbering.
    DATABASES["default"].setdefault("OPTIONS", {})["transaction_mode"] = "IMMEDIATE"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Casablanca"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    # "default" doit être déclaré explicitement dès que STORAGES est défini,
    # sinon les FileField (documents joints) n'ont plus de stockage.
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    # Cabinet : fichiers versionnés et compressés (après collectstatic). Développement et tests :
    # servis tels quels depuis static/, sans manifeste à régénérer.
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# Adresse joignable depuis un téléphone du cabinet (ex. http://192.168.1.20:8000) pour le QR code
# « Envoyer depuis le téléphone ». Vide : adresse de la requête courante.
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", default="")


def _lan_address():
    """IP du poste sur le réseau local (aucun paquet envoyé : simple choix de route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# « auto » : adresse recalculée à chaque démarrage du serveur, si la box change l'IP du poste.
if PUBLIC_BASE_URL.startswith("auto"):
    PUBLIC_BASE_URL = f"http://{_lan_address()}:{env.int('MEDIGEST_PORT', default=8000)}"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:post_login_redirect"
LOGOUT_REDIRECT_URL = "accounts:login"

# URL path prefixes considered clinical and off-limits to the "assistant" role.
# Enforced unconditionally by apps.accounts.middleware.ClinicalAccessMiddleware,
# in addition to the @role_required decorator on individual views.
CLINICAL_URL_PREFIXES = ["/clinical/"]

# Journal des erreurs au cabinet : logs\medigest.log (5 fichiers de 2 Mo max), jamais de données patientes.
if not DEBUG:
    LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"simple": {"format": "{asctime} {levelname} {name} : {message}", "style": "{"}},
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": LOG_DIR / "medigest.log",
                "maxBytes": 2 * 1024 * 1024,
                "backupCount": 5,
                "encoding": "utf-8",
                "formatter": "simple",
            },
        },
        "root": {"handlers": ["file"], "level": "WARNING"},
        "loggers": {"waitress": {"handlers": ["file"], "level": "INFO", "propagate": False}},
    }
