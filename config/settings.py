"""
Configuración principal del proyecto CESFAM Farmacia Web.
Sistema de Gestión y Simulación Asistencial para Farmacia de APS.
Autores: Egon Muñoz Muttel y Renato Suazo Burgos - INACAP 2026
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga liviana de variables desde .env local (opcional, sin dependencias externas)
_env_file = BASE_DIR / '.env'
if _env_file.exists():
    for _raw in _env_file.read_text(encoding='utf-8').splitlines():
        _line = _raw.strip()
        if not _line or _line.startswith('#') or '=' not in _line:
            continue
        _k, _v = _line.split('=', 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-cesfam-2026-egon-renato-proyecto-integrado-inacap',
)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 'yes')

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',') if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party
    'rest_framework',
    'django_filters',
    'corsheaders',
    # Apps del proyecto
    'core.apps.CoreConfig',
    'farmacia.apps.FarmaciaConfig',
    'dispensacion.apps.DispensacionConfig',
    'ges.apps.GesConfig',
    'controlados.apps.ControladosConfig',
    'carros_clinicos.apps.CarrosClinicosConfig',
    'reportes.apps.ReportesConfig',
    'api.apps.ApiConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.AuditMiddleware',
    'core.middleware.SecurityHeadersMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'OPTIONS': {
            'loaders': [
                'django.template.loaders.filesystem.Loader',
                'django.template.loaders.app_directories.Loader',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.global_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- Base de Datos Relacional (SQLite por defecto para inicio rápido; PostgreSQL vía .env) ---
DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite').strip().lower()
if DB_ENGINE == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'cesfam_farmacia_db'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# --- Base de Datos Documental (MongoDB opcional con fallback local) ---
MONGODB_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/')
MONGODB_NAME = os.environ.get('MONGODB_NAME', 'cesfam_nosql_db')

# --- Seguridad de contraseñas (Argon2 + PBKDF2) ---
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Modelo de usuario personalizado ---
AUTH_USER_MODEL = 'core.Usuario'

# --- Internacionalización ---
LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos ---
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- REST Framework ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
    'DATETIME_FORMAT': '%d/%m/%Y %H:%M',
}

# --- Login / Logout ---
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# --- Cabeceras de seguridad ---
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Cifrado simétrico (Fernet/AES) para datos sensibles - Ley 21.719 ---
FERNET_KEY = os.environ.get('FERNET_KEY', 'FF4L3jxoeRGOG8AUMaRVygz9XemP2QQVoRcoRLwZpIs=')

# --- CORS ---
CORS_ALLOW_ALL_ORIGINS = True  # Solo desarrollo

# --- Simulación Docente: Selector rápido de 1 clic ---
# False (recomendado): solo el Administrador real autenticado puede usar /simular-rol/ (403 a otros roles).
# True: habilita el cambio rápido de rol en /login/ y barra superior para demostraciones abiertas.
MODO_SIMULACION_DOCENTE = os.environ.get('MODO_SIMULACION_DOCENTE', 'False').lower() in ('true', '1', 'yes')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
