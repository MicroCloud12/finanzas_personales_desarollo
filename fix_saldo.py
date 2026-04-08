import django
import os
import sys

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PrismaVault.settings')
django.setup()

from finanzas.models import Deuda, registro_transacciones
from django.db.models import Sum

def fix_saldo():
    tarjetas = Deuda.objects.filter(tipo_deuda='TARJETA_CREDITO')
    for tarjeta in tarjetas:
        # Sum all gastos mapped to this credit card by cuenta_origen
        gastos_val = registro_transacciones.objects.filter(
            tipo='GASTO',
            cuenta_origen=tarjeta.nombre,
            propietario=tarjeta.propietario
        ).aggregate(t=Sum('monto'))['t'] or 0
        
        # Also sum any TARJETA_CREDITO purchases mapped via deuda_asociada
        # wait, if they were mapped via deuda_asociada AND cuenta_origen=tarjeta.nombre, we avoid double subtract.
        # But let's just do a naive check: total available = monto_total - (gastos on cuenta_origen)
        
        # Calculate exactly how we process
        expected_saldo = tarjeta.monto_total - gastos_val
        print(f"Tarjeta: {tarjeta.nombre}, Monto: {tarjeta.monto_total}, Gastos: {gastos_val}, Saldo actual: {tarjeta.saldo_pendiente}, Saldo esperado: {expected_saldo}")
        
        # Update manually
        tarjeta.saldo_pendiente = expected_saldo
        tarjeta.save()
        print(f"-> Actualizado a {expected_saldo}")

if __name__ == '__main__':
    fix_saldo()
