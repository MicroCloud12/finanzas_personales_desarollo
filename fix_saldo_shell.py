from finanzas.models import Deuda, registro_transacciones
from django.db.models import Sum

tarjetas = Deuda.objects.filter(tipo_deuda='TARJETA_CREDITO')
for tarjeta in tarjetas:
    gastos_val = registro_transacciones.objects.filter(
        tipo='GASTO',
        cuenta_origen=tarjeta.nombre,
        propietario=tarjeta.propietario
    ).aggregate(t=Sum('monto'))['t'] or 0
    
    expected_saldo = (tarjeta.monto_total or 0) - gastos_val
    print(f"Tarjeta: {tarjeta.nombre}, Monto: {tarjeta.monto_total}, Gastos: {gastos_val}, Saldo actual: {tarjeta.saldo_pendiente}, Saldo esperado: {expected_saldo}")
    
    tarjeta.saldo_pendiente = expected_saldo
    tarjeta.save()
    print(f"-> Actualizado a {expected_saldo}")
