from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
import os
import sys

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv()
NPM_BIN_PATH = r"C:\Program Files\nodejs\npm.cmd"

SECRET_KEY = os.getenv("SECRET_KEY")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(',')

# Llave maestra para desenvolver las llaves de cifrado por usuario (MultiFernet: soporta rotación con comas).
_RUNNING_TESTS = "test" in sys.argv
_BUILD_CMDS = {"collectstatic", "generar_llave_cifrado", "help"}
DATA_ENCRYPTION_KEY = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
if not DATA_ENCRYPTION_KEY and _RUNNING_TESTS:
    # Llave determinista exclusiva para pruebas automatizadas cuando no viene en entorno.
    DATA_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
elif not DATA_ENCRYPTION_KEY and not DEBUG and not (_BUILD_CMDS & set(sys.argv[1:])):
    raise ImproperlyConfigured(
        "Falta DATA_ENCRYPTION_KEY en las variables de entorno. "
        "Genera una con: python manage.py generar_llave_cifrado"
    )

# ngrok (u otro proxy) recibe HTTPS y reenvía en HTTP con X-Forwarded-Proto: https.
# Sin esto Django cree que la petición es http y allauth manda a Google un
# redirect_uri "http://..." que no coincide con el registrado (redirect_uri_mismatch).
# El acceso directo por http://localhost:8000 sigue funcionando igual.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'tailwind',
    'theme',
    'finanzas',
    'allauth',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sitemaps',  # plantilla de /sitemap.xml
    'django.contrib.sites', # Requerido por allauth
    'allauth.account',
    'allauth.socialaccount',
    # Proveedor específico de Google
    'allauth.socialaccount.providers.google',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django_session_timeout.middleware.SessionTimeoutMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

if _RUNNING_TESTS and os.getenv("USE_SQLITE_TESTS") == "1":
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
    MIGRATION_MODULES = {'finanzas': None}
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv("DB_NAME"),
            'USER': os.getenv("DB_USER"),
            'PASSWORD': os.getenv("DB_PASSWORD"),
            'HOST': os.getenv("DB_HOST"),
            'PORT': os.getenv("DB_PORT"),
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'      # destino de collectstatic
STATICFILES_DIRS = [BASE_DIR / 'static']

# WhiteNoise: archivos comprimidos y con hash en el nombre (caché larga).
STORAGES = {
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if _RUNNING_TESTS
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'home'
TAILWIND_APP_NAME = 'theme'

# --- CELERY ---
# En Docker, docker-compose define CELERY_BROKER_URL=redis://redis:6379/0
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'


SITE_ID = 1
# Allauth Settings
ACCOUNT_EMAIL_VERIFICATION = 'optional' # Puedes cambiarlo a 'mandatory' si quieres verificación de email
ACCOUNT_LOGOUT_ON_GET = True # Permite el logout con GET para simplificar

# Permiso para leer Drive. Google lo clasifica como "restringido" (verificación con auditoría de
# seguridad), así que NO va en el login: se pide aparte, solo a quien pulse "Conectar Google Drive"
# (ver url_conectar_drive en finanzas/templatetags/drive_tags.py y la vista drive_conectado).
GOOGLE_DRIVE_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        # Solo identidad: no sensible para Google, sin pantalla de "app no verificada".
        'SCOPE': ['profile', 'email'],
        'OAUTH_PKCE_ENABLED': True,
        # Si Google confirma (email verificado) un correo que ya pertenece a un
        # usuario local, inicia sesión en ese usuario en vez de mandar al
        # formulario de registro. Solo para Google, que verifica los correos.
        'EMAIL_AUTHENTICATION': True,
    }
}

# Al entrar por correo, vincula la cuenta de Google al usuario existente para
# guardar sus tokens (los necesita el acceso a Drive).
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_STORE_TOKENS = True
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CSRF_TRUSTED_ORIGINS = os.getenv("CSRF_TRUSTED_ORIGINS", '').split(',')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'debug.log', # El archivo se creará en la raíz de tu proyecto
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'finanzas': {
            'handlers': ['console', 'file'], # Envía los logs a la consola y al archivo
            'level': 'DEBUG', # Captura desde el nivel más bajo (DEBUG)
            'propagate': False,
        },
    },
}


# Email configuration
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND')
EMAIL_HOST = os.getenv('EMAIL_HOST')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# --- DJANGO SESSION TIMEOUT SETTINGS ---
# Tiempo en segundos que una sesión puede estar inactiva. 
# Después de este tiempo, el usuario tendrá que volver a iniciar sesión.
SESSION_EXPIRE_SECONDS = 1800  # 30 minutos (30 * 60)

# Si es True, la sesión expira después del tiempo definido en SESSION_EXPIRE_SECONDS
# desde la última actividad del usuario. Si es False, expira desde el inicio de sesión.
SESSION_EXPIRE_AFTER_LAST_ACTIVITY = True

# URL a la que se redirige al usuario cuando su sesión expira.
SESSION_TIMEOUT_REDIRECT = 'login' 