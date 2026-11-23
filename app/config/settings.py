"""Django sozlamalari. Barcha maxfiy qiymatlar muhit o'zgaruvchilaridan olinadi."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path):
    """Lokal ishga tushirish uchun app/.env faylini o'qiydi (muhit o'zgaruvchilari ustun)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY berilmagan")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "vision",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if not DEBUG:  # lokal (DEBUG) rejimda statik fayllarni runserver beradi
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if os.environ.get("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "davomat"),
            "USER": os.environ.get("DB_USER", "davomat"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ["DB_HOST"],
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            "CONN_HEALTH_CHECKS": True,
        }
    }
else:
    # Faqat lokal ishlab chiqish va testlar uchun
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("SQLITE_PATH", BASE_DIR / "dev.sqlite3"),
            # Veb-server va worker ikki alohida jarayon: WAL va IMMEDIATE tranzaksiyalar
            # bloklanishni kamaytiradi
            "OPTIONS": {
                "timeout": 20,
                "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
                "transaction_mode": "IMMEDIATE",
            },
        }
    }

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Maxfiylik: yuklangan yuz rasmlari faqat xotirada ishlanadi, diskka yozilmaydi ---
FILE_UPLOAD_HANDLERS = ["core.uploads.MemoryOnlyUploadHandler"]
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
MAX_FACE_SAMPLE_BYTES = 10 * 1024 * 1024

# --- Xavfsizlik (HTTPS proxy ortida) ---
if env_bool("DJANGO_SECURE", not DEBUG):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# --- Shifrlash kalitlari (andozalar, RTSP rekvizitlari) ---
FIELD_ENCRYPTION_KEYS = env_list("FIELD_ENCRYPTION_KEYS", "")

# --- Yuzni tanish modellari ---
FACE_MODELS_DIR = Path(os.environ.get("FACE_MODELS_DIR", BASE_DIR / "models"))
YUNET_MODEL = FACE_MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = FACE_MODELS_DIR / "face_recognition_sface_2021dec.onnx"
FACE_MODEL_VERSION = "sface_2021dec+yunet_2023mar"

# --- Worker ---
WORKER_THREADS = int(os.environ.get("WORKER_THREADS", "2"))
WORKER_POLL_SECONDS = float(os.environ.get("WORKER_POLL_SECONDS", "1.0"))
# Jonli ko'rish: worker ichidagi HTTP server (kadrlar faqat xotirada, token bilan himoyalangan)
CAMERA_PREVIEW_ENABLED = env_bool("CAMERA_PREVIEW_ENABLED", True)
WORKER_PREVIEW_BIND = os.environ.get("WORKER_PREVIEW_BIND", "127.0.0.1")  # worker tinglaydigan manzil
WORKER_PREVIEW_HOST = os.environ.get("WORKER_PREVIEW_HOST", "127.0.0.1")  # veb-ilova murojaat qiladigan manzil
WORKER_PREVIEW_PORT = int(os.environ.get("WORKER_PREVIEW_PORT", "8765"))
# Brauzer so'rov davri (ms)
UI_POLL_INTERVAL_MS = int(os.environ.get("UI_POLL_INTERVAL_MS", "2000"))

# Loglarda shaxsiy ma'lumot yo'q: faqat ID lar yoziladi.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
