import os
# Settings de prueba: SQLite en memoria, sin servicios externos.
from config.settings import *  # noqa
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
CELERY_TASK_ALWAYS_EAGER = True
SECRET_KEY = 'test'
DEBUG = True
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
COMPRESS_ENABLED = False
USE_I18N = False
CSRF_TRUSTED_ORIGINS = ['http://localhost']
ALLOWED_HOSTS = ['*']
# La cadena de migraciones histórica no corre en una BD vacía (0001/0002 duplican
# TransaccionPendiente); las pruebas crean las tablas directo desde los modelos.
MIGRATION_MODULES = {"finanzas": None} if os.environ.get("SIN_MIGRACIONES", "1") == "1" else {}
