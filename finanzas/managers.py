from django.db import models
from django.db.models import Sum, Q, F
from django.utils import timezone
from datetime import datetime

class TransaccionManager(models.Manager):
    """
    Manager personalizado para encapsular consultas complejas de transacciones.
    Optimiza la legibilidad de las views y centraliza la lógica de negocio.
    """
    
    def del_mes(self, usuario, year=None, month=None):
        """Retorna queryset filtrado por usuario y fecha (año/mes)."""
        now = timezone.now()
        year = year or now.year
        month = month or now.month
        return self.filter(propietario=usuario, fecha__year=year, fecha__month=month)

    def balance_dashboard(self, usuario, year=None, month=None):
        """
        Calcula todos los totales necesarios para el dashboard en UNA sola consulta a la DB.
        Retorna un diccionario con los valores listos.
        """
        # Obtenemos el queryset base del mes
        qs = self.del_mes(usuario, year, month)
        
        # Realizamos la agregación masiva
        # filter=Q(...) es mucho más rápido que hacer filter cerparados en Python
        agregados = qs.aggregate(
            ingresos_efectivo=Sum('monto', filter=Q(tipo='INGRESO') & ~Q(categoria='Ahorro') & Q(cuenta_origen='Efectivo Quincena')),
            gastos_efectivo=Sum('monto', filter=Q(tipo='GASTO') & ~Q(categoria='Ahorro') & Q(cuenta_origen='Efectivo Quincena')),
            ahorro_total=Sum('monto', filter=Q(tipo='TRANSFERENCIA', categoria='Ahorro', cuenta_origen='Efectivo Quincena', cuenta_destino='Cuenta Ahorro')),
            transferencias_efectivo=Sum('monto', filter=Q(tipo='TRANSFERENCIA') & ~Q(categoria='Ahorro') & Q(cuenta_origen='Efectivo Quincena')),
            gastos_ahorro=Sum('monto', filter=Q(tipo='GASTO', cuenta_origen='Cuenta Ahorro')),
            ingresos_ahorro=Sum('monto', filter=Q(tipo='INGRESO', cuenta_origen='Cuenta Ahorro')),
        )
        
        # Limpiamos los None (si no hay datos devuelve None, queremos 0)
        return {k: (v or 0) for k, v in agregados.items()}

    def gastos_por_categoria(self, usuario, year, month):
        """Retorna lista de diccionarios para gráficas: [{'categoria': 'X', 'total': 100}, ...]"""
        return (self.del_mes(usuario, year, month)
                .filter(tipo='GASTO')
                .values('categoria')
                .annotate(total=Sum('monto'))
                .order_by('-total'))

    def ahorro_acumulado_anual(self, usuario, year):
        """
        Calcula el crecimiento del ahorro mes a mes para una gráfica.
        """
        from django.db.models.functions import TruncMonth
        
        return (self.filter(propietario=usuario, fecha__year=year)
                .filter(
                    (Q(categoria__iexact='Ahorro') & ~Q(tipo__iexact='GASTO')) |
                    Q(tipo__iexact='TRANSFERENCIA', cuenta_destino__iexact='Cuenta Ahorro') | 
                    Q(tipo__iexact='INGRESO', cuenta_origen__iexact='Cuenta Ahorro')
                )
                .annotate(mes=TruncMonth('fecha'))
                .values('mes')
                .annotate(total=Sum('monto'))
                .order_by('mes'))
