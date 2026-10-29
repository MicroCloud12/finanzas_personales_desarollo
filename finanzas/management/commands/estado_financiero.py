"""
Estados financieros personales a partir del libro mayor.

    python manage.py estado_financiero --usuario mauricio            # mes actual
    python manage.py estado_financiero --usuario mauricio --mes 2026-09

Imprime:
  1. Estado de resultados del mes (ingresos, gastos por categoría, intereses, resultado)
     comparado con el mes anterior.
  2. Balance general al cierre del mes (activos, pasivos, patrimonio).
  3. Flujo de efectivo: cuánto fue a ahorro, cuánto a pagar deuda.
"""
import calendar
from datetime import date, datetime

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from finanzas.models import Cuenta, registro_transacciones


def _fila(nombre, actual, anterior=None, ancho=34):
    if anterior is None:
        return f"  {nombre:<{ancho}} {actual:>14,.2f}"
    dif = actual - anterior
    pct = (dif / anterior * 100) if anterior else 0
    return f"  {nombre:<{ancho}} {actual:>14,.2f} {anterior:>14,.2f} {dif:>+12,.2f} {pct:>+7.1f}%"


class Command(BaseCommand):
    help = "Estado de resultados, balance general y flujo de efectivo del mes."

    def add_arguments(self, parser):
        parser.add_argument('--usuario', required=True)
        parser.add_argument('--mes', default=None, help='YYYY-MM (por defecto el mes actual)')

    def handle(self, *args, **opts):
        try:
            user = User.objects.get(username=opts['usuario'])
        except User.DoesNotExist:
            raise CommandError(f"No existe el usuario {opts['usuario']!r}")

        if opts['mes']:
            year, month = (int(x) for x in opts['mes'].split('-'))
        else:
            hoy = datetime.now()
            year, month = hoy.year, hoy.month
        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        fin_mes = date(year, month, calendar.monthrange(year, month)[1])

        tx = registro_transacciones.objects
        act = tx.balance_dashboard(user, year, month)
        ant = tx.balance_dashboard(user, prev_year, prev_month)

        w = self.stdout.write
        w(self.style.MIGRATE_HEADING(f"\nESTADO DE RESULTADOS — {year}-{month:02d} (vs {prev_year}-{prev_month:02d})"))
        w(f"  {'':<34} {'Actual':>14} {'Anterior':>14} {'Var $':>12} {'Var %':>8}")
        w(_fila('Ingresos', act['ingresos'], ant['ingresos']))
        w("  Gastos por categoría:")
        for fila in tx.gastos_por_categoria(user, year, month):
            w(_fila(f"    {fila['categoria'][:28]}", fila['total']))
        w(_fila('Gastos de consumo', act['gastos_consumo'], ant['gastos_consumo']))
        w(_fila('  (de los cuales con tarjeta)', act['gastos_tarjeta'], ant['gastos_tarjeta']))
        w(_fila('Intereses de deuda', act['intereses'], ant['intereses']))
        w(_fila('TOTAL GASTOS', act['gastos'], ant['gastos']))
        w(self.style.SUCCESS(_fila('RESULTADO DEL MES', act['resultado'], ant['resultado'])))

        w(self.style.MIGRATE_HEADING(f"\nFLUJO DE EFECTIVO — {year}-{month:02d}"))
        w(_fila('Resultado del mes', act['resultado']))
        w(_fila('Ahorro neto (a cuentas de ahorro)', act['ahorro_neto']))
        w(_fila('Pagos a deuda (tarjetas + préstamos)', act['pagos_deuda']))
        w(_fila('  de los cuales abono a capital', act['abonos_capital']))

        resumen = Cuenta.objects.resumen_balance(user, hasta=fin_mes)
        w(self.style.MIGRATE_HEADING(f"\nBALANCE GENERAL al {fin_mes:%d/%m/%Y}"))
        w("  ACTIVOS")
        for c in resumen['cuentas']:
            if c.es_activo:
                w(_fila(f"    {c.nombre[:30]}", c.saldo_calculado))
        w(_fila('  Total activos', resumen['activos']))
        w("  PASIVOS")
        for c in resumen['cuentas']:
            if c.es_pasivo:
                w(_fila(f"    {c.nombre[:30]}", c.saldo_calculado))
        w(_fila('  Total pasivos', resumen['pasivos']))
        w(self.style.SUCCESS(_fila('PATRIMONIO NETO (activos - pasivos)', resumen['patrimonio'])))
        w("")
