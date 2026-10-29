"""
Conciliación de saldos del libro mayor contra la realidad (estado de cuenta).

    python manage.py conciliar_saldos
        Reporte de TODOS los usuarios: cada cuenta con su saldo derivado del
        libro y los nombres de cuenta de movimientos antiguos que no se
        pudieron ligar a ninguna cuenta.

    python manage.py conciliar_saldos --usuario mauricio
        Lo mismo, solo para ese usuario (username con el que inicia sesión).

    python manage.py conciliar_saldos --usuario mauricio --set "BBVA=12345.67" --set "Tarjeta Nu=2300"
        Fija el saldo REAL de hoy de esas cuentas (activo: lo que hay;
        pasivo: lo que se debe). El comando ajusta `saldo_inicial` para que el
        saldo derivado coincida y reporta la partida conciliatoria.

    python manage.py conciliar_saldos --usuario mauricio --ligar "Efectivo Quincena=Efectivo"
        Liga los movimientos antiguos capturados con el nombre "Efectivo Quincena"
        (texto) a la cuenta "Efectivo" del catálogo.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from finanzas.models import Cuenta, registro_transacciones


class Command(BaseCommand):
    help = "Concilia los saldos derivados del libro mayor contra los saldos reales."

    def add_arguments(self, parser):
        parser.add_argument('--usuario', default=None,
                            help='username del propietario. Si se omite, el reporte es de todos los usuarios '
                                 '(obligatorio para --set y --ligar)')
        parser.add_argument('--set', action='append', default=[], metavar='CUENTA=SALDO',
                            help='Saldo real de hoy para esa cuenta (se puede repetir)')
        parser.add_argument('--ligar', action='append', default=[], metavar='NOMBRE_VIEJO=CUENTA',
                            help='Liga movimientos antiguos con ese nombre de texto a una cuenta del catálogo')

    def handle(self, *args, **opts):
        if opts['usuario'] is None:
            if opts['set'] or opts['ligar']:
                raise CommandError("--set y --ligar modifican datos de un usuario: indica --usuario <username>")
            usuarios = User.objects.filter(cuenta__isnull=False).distinct().order_by('username')
            if not usuarios:
                self.stdout.write("No hay usuarios con cuentas registradas.")
            for user in usuarios:
                self._reporte(user)
            return

        try:
            user = User.objects.get(username=opts['usuario'])
        except User.DoesNotExist:
            disponibles = ", ".join(User.objects.values_list('username', flat=True)[:20])
            raise CommandError(f"No existe el usuario {opts['usuario']!r}. Usuarios registrados: {disponibles}")

        for par in opts['ligar']:
            self._ligar(user, par)
        for par in opts['set']:
            self._set(user, par)

        self._reporte(user)

    # ------------------------------------------------------------------
    def _cuenta(self, user, nombre):
        cuenta = Cuenta.objects.filter(propietario=user, nombre__iexact=nombre.strip()).first()
        if cuenta is None:
            raise CommandError(f"No existe la cuenta {nombre!r} para {user.username}")
        return cuenta

    def _ligar(self, user, par):
        if '=' not in par:
            raise CommandError("--ligar espera NOMBRE_VIEJO=CUENTA")
        viejo, nuevo = [x.strip() for x in par.split('=', 1)]
        cuenta = self._cuenta(user, nuevo)
        qs = registro_transacciones.objects.filter(propietario=user)
        n_origen = qs.filter(origen__isnull=True, cuenta_origen__iexact=viejo).exclude(tipo='INGRESO').update(origen=cuenta)
        n_destino = qs.filter(destino__isnull=True).filter(
            Q(cuenta_destino__iexact=viejo) | Q(tipo='INGRESO', cuenta_origen__iexact=viejo)).update(destino=cuenta)
        self.stdout.write(self.style.SUCCESS(
            f"Ligados a '{cuenta.nombre}': {n_origen} movimientos como origen y {n_destino} como destino."))

    def _set(self, user, par):
        if '=' not in par:
            raise CommandError("--set espera CUENTA=SALDO")
        nombre, saldo = [x.strip() for x in par.split('=', 1)]
        cuenta = self._cuenta(user, nombre)
        try:
            saldo_real = Decimal(saldo.replace(',', ''))
        except Exception:
            raise CommandError(f"Saldo inválido: {saldo!r}")
        antes = cuenta.saldo()
        diferencia = cuenta.ajustar_saldo_inicial_para(saldo_real)
        self.stdout.write(self.style.SUCCESS(
            f"{cuenta.nombre}: saldo según libro {antes:,.2f} -> real {saldo_real:,.2f} "
            f"(partida conciliatoria {diferencia:+,.2f}; saldo inicial ahora {cuenta.saldo_inicial:,.2f})"))

    def _reporte(self, user):
        resumen = Cuenta.objects.resumen_balance(user)
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Saldos según el libro mayor — {user.username}"))
        for c in resumen['cuentas']:
            etiqueta = 'DEBE ' if c.es_pasivo else 'SALDO'
            self.stdout.write(f"  [{c.get_tipo_display():<26}] {c.nombre:<30} {etiqueta} {c.saldo_calculado:>14,.2f}"
                              f"   (inicial {c.saldo_inicial:,.2f})")
        self.stdout.write(f"  {'Activos':<58} {resumen['activos']:>14,.2f}")
        self.stdout.write(f"  {'Pasivos':<58} {resumen['pasivos']:>14,.2f}")
        self.stdout.write(f"  {'Patrimonio neto':<58} {resumen['patrimonio']:>14,.2f}")

        huerfanos = registro_transacciones.objects.filter(propietario=user).filter(
            Q(origen__isnull=True, destino__isnull=True))
        if huerfanos.exists():
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"{huerfanos.count()} movimientos no están ligados a ninguna cuenta (no afectan saldos). "
                "Nombres capturados originalmente:"))
            nombres = {}
            for t in huerfanos.values_list('cuenta_origen', 'cuenta_destino'):
                for n in t:
                    if n:
                        nombres[n] = nombres.get(n, 0) + 1
            for n, k in sorted(nombres.items(), key=lambda x: -x[1]):
                self.stdout.write(f"    - {n!r}: {k}  -> usa --ligar \"{n}=<cuenta>\"")
