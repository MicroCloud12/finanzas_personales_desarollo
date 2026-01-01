from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from finanzas.models import PortfolioHistory
from finanzas.utils import calculate_daily_portfolio_history
import time

class Command(BaseCommand):
    help = 'Calcula y almacena el historial diario del portafolio para todos los usuarios.'

    def handle(self, *args, **kwargs):
        usuarios = User.objects.all()
        for usuario in usuarios:
            self.stdout.write(self.style.SUCCESS(f'Procesando historial diario para: {usuario.username}'))
            
            # 1. Calculamos la historia diaria
            # Esto puede tardar varios minutos la primera vez debido a las pausas de la API
            historial = calculate_daily_portfolio_history(usuario)
            
            if not historial:
                self.stdout.write(self.style.WARNING(f'No hay inversiones para {usuario.username}.'))
                continue

            # 2. Borramos historial antiguo (o podríamos hacer upsert, pero esto es más limpio para re-calcular)
            PortfolioHistory.objects.filter(usuario=usuario).delete()
            
            # 3. Guardamos los nuevos datos en batch
            batch = []
            for dia in historial:
                batch.append(PortfolioHistory(
                    usuario=usuario,
                    fecha=dia['fecha'],
                    valor_total=dia['valor_total'],
                    capital_invertido=dia['capital_invertido'],
                    ganancia_no_realizada=dia['ganancia_no_realizada']
                ))
            
            PortfolioHistory.objects.bulk_create(batch)
            self.stdout.write(f'Se guardaron {len(batch)} registros diarios para {usuario.username}.')
        
        self.stdout.write(self.style.SUCCESS('Proceso de historial completado.'))
