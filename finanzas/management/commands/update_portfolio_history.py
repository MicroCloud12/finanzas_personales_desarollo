from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from finanzas.tasks import guardar_historial_portafolio

class Command(BaseCommand):
    help = 'Calcula y almacena el historial diario del portafolio para todos los usuarios.'

    def handle(self, *args, **kwargs):
        for usuario in User.objects.all():
            self.stdout.write(self.style.SUCCESS(f'Procesando historial diario para: {usuario.username}'))
            # Puede tardar varios minutos la primera vez por las pausas de la API
            registros = guardar_historial_portafolio(usuario)
            if registros:
                self.stdout.write(f'Se guardaron {registros} registros diarios para {usuario.username}.')
            else:
                self.stdout.write(self.style.WARNING(f'No hay inversiones para {usuario.username}.'))
        self.stdout.write(self.style.SUCCESS('Proceso de historial completado.'))
