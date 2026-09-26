import time
from decimal import Decimal
from django.core.management.base import BaseCommand
from finanzas.models import inversiones
from finanzas.services import StockPriceService

class Command(BaseCommand):
    help = "Actualiza el precio actual de todas las inversiones en la base de datos usando la API de Twelve Data."

    def handle(self, *args, **kwargs):
        self.stdout.write(
            self.style.SUCCESS(
                "Iniciando la actualización de precios de inversiones..."
            )
        )
        # Obtenemos todas las inversiones que son de tipo 'Acción'
        investment_list = inversiones.objects.filter()
        
        if not investment_list:
            self.stdout.write(
                    self.style.WARNING(
                        'No se encontraron inversiones para actualizar.'
                    )
                )
            return
            

        price_service = StockPriceService()
        updated_count = 0
                
        # Iteramos sobre cada inversión
        for investment in investment_list:
            ticker = investment.emisora_ticker

            if not ticker:
                continue # Saltamos si no tiene un ticker

            self.stdout.write(f"  - Obteniendo precio para {ticker}...", ending="")
            # Obtenemos el precio desde nuestro servicio
            new_price_float = price_service.get_current_price(ticker)

            if new_price_float is not None:
                # Convertimos a Decimal y actualizamos el modelo
                investment.precio_actual_titulo = Decimal(str(new_price_float))
                investment.save()  # .save() recalculará el valor de mercado y la ganancia/pérdida

                self.stdout.write(
                    self.style.SUCCESS(f" ¡Actualizado a ${new_price_float:.2f}!"))
                
                updated_count += 1
                
            else:
                self.stdout.write(self.style.ERROR(" ¡Falló!"))

            # La API gratuita de Alpha Vantage tiene un límite de 5 llamadas por minuto.
            # Añadimos una pausa de 15 segundos para no exceder el límite.
            time.sleep(5)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nProceso completado. Se actualizaron {updated_count} de {len(investment_list)} inversiones."

            )
        )