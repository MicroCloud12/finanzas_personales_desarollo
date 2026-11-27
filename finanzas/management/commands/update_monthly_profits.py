# EN: finanzas/management/commands/update_monthly_profits.py

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from finanzas.models import GananciaMensual
from finanzas.utils import calculate_monthly_profit
import time

class Command(BaseCommand):
    help = 'Calcula y almacena las ganancias mensuales no realizadas para todos los usuarios.'

    def handle(self, *args, **kwargs):
        usuarios = User.objects.all()
        for usuario in usuarios:
            self.stdout.write(self.style.SUCCESS(f'Procesando usuario: {usuario.username}'))
            
            # 1. Borramos los datos antiguos para este usuario
            GananciaMensual.objects.filter(propietario=usuario).delete()
            
            # 2. Calculamos los nuevos datos (aquí se hacen las llamadas a la API)
            ganancias = calculate_monthly_profit(usuario)
            print(f'Ganancias calculadas para {usuario}: {ganancias}')
            time.sleep(15)
            # 3. Guardamos los nuevos datos en nuestra tabla
            for mes, total in ganancias.items():
                GananciaMensual.objects.create(
                    propietario=usuario,
                    mes=mes,
                    total=total
                )
            self.stdout.write(f'Se guardaron {len(ganancias)} registros de ganancias mensuales para {usuario.username}.')
        
        self.stdout.write(self.style.SUCCESS('Proceso completado.'))