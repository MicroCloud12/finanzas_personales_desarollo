from django.apps import AppConfig


class FinanzasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finanzas'

    def ready(self):
        from . import signals  # noqa: F401  (registra la señal que conserva drive_ok)
