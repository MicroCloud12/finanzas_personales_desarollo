"""
Pruebas del libro mayor: saldos derivados, partida doble simplificada,
pagos de deuda divididos en capital/interés, dashboard y migración de datos.

Correr:  python manage.py test finanzas.tests_libro_mayor
"""
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import TransaccionesForm
from .migrations import _libro_mayor
from .models import Cuenta, Deuda, PagoAmortizacion, registro_transacciones

D = Decimal


def tx(user, tipo, monto, origen=None, destino=None, fecha=date(2026, 10, 10), categoria='Varios', **extra):
    return registro_transacciones.objects.create(
        propietario=user, fecha=fecha, descripcion=f'{tipo} {monto}', categoria=categoria,
        monto=D(str(monto)), tipo=tipo, origen=origen, destino=destino, **extra)


class BaseLibro(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.debito = Cuenta.objects.create(propietario=self.user, nombre='BBVA', tipo='DEBITO', saldo_inicial=D('1000'))
        self.efectivo = Cuenta.objects.create(propietario=self.user, nombre='Efectivo', tipo='EFECTIVO')
        self.ahorro = Cuenta.objects.create(propietario=self.user, nombre='Ahorro Nu', tipo='AHORRO')
        self.tarjeta_deuda = Deuda.objects.create(
            propietario=self.user, nombre='Tarjeta Nu', tipo_deuda='TARJETA_CREDITO',
            monto_total=D('20000'), tasa_interes=D('60'), plazo_meses=1)
        self.tarjeta = self.tarjeta_deuda.cuenta


class SaldosDerivadosTest(BaseLibro):

    def test_ingreso_entra_a_destino(self):
        tx(self.user, 'INGRESO', 500, destino=self.debito)
        self.assertEqual(self.debito.saldo(), D('1500'))

    def test_gasto_sale_de_origen(self):
        tx(self.user, 'GASTO', 200, origen=self.debito)
        self.assertEqual(self.debito.saldo(), D('800'))

    def test_transferencia_mueve_entre_cuentas(self):
        tx(self.user, 'TRANSFERENCIA', 300, origen=self.debito, destino=self.efectivo)
        self.assertEqual(self.debito.saldo(), D('700'))
        self.assertEqual(self.efectivo.saldo(), D('300'))

    def test_editar_monto_corrige_saldo_sin_revertir_nada(self):
        movimiento = tx(self.user, 'GASTO', 200, origen=self.debito)
        movimiento.monto = D('350')
        movimiento.save()
        self.assertEqual(self.debito.saldo(), D('650'))
        # cambiar la cuenta también se refleja
        movimiento.origen = self.efectivo
        movimiento.save()
        self.assertEqual(self.debito.saldo(), D('1000'))
        self.assertEqual(self.efectivo.saldo(), D('-350'))

    def test_borrar_movimiento_restaura_saldo(self):
        movimiento = tx(self.user, 'GASTO', 200, origen=self.debito)
        movimiento.delete()
        self.assertEqual(self.debito.saldo(), D('1000'))

    def test_saldo_a_una_fecha(self):
        tx(self.user, 'GASTO', 100, origen=self.debito, fecha=date(2026, 9, 1))
        tx(self.user, 'GASTO', 100, origen=self.debito, fecha=date(2026, 10, 1))
        self.assertEqual(self.debito.saldo(hasta=date(2026, 9, 30)), D('900'))
        self.assertEqual(self.debito.saldo(), D('800'))

    def test_conciliacion_ajusta_saldo_inicial(self):
        tx(self.user, 'GASTO', 200, origen=self.debito)
        diferencia = self.debito.ajustar_saldo_inicial_para(D('5000'))
        self.assertEqual(diferencia, D('4200'))
        self.assertEqual(self.debito.saldo(), D('5000'))
        self.assertEqual(self.debito.saldo_inicial, D('5200'))

    def test_resumen_balance(self):
        tx(self.user, 'TRANSFERENCIA', 300, origen=self.debito, destino=self.ahorro)
        tx(self.user, 'GASTO', 150, origen=self.tarjeta)
        resumen = Cuenta.objects.resumen_balance(self.user)
        self.assertEqual(resumen['activos'], D('1000'))      # 700 débito + 300 ahorro
        self.assertEqual(resumen['liquido'], D('700'))
        self.assertEqual(resumen['ahorro'], D('300'))
        self.assertEqual(resumen['pasivos'], D('150'))
        self.assertEqual(resumen['patrimonio'], D('850'))


class TarjetaCreditoTest(BaseLibro):

    def test_deuda_crea_su_cuenta_de_pasivo(self):
        self.assertIsNotNone(self.tarjeta)
        self.assertEqual(self.tarjeta.tipo, 'CREDITO')
        self.assertEqual(self.tarjeta_deuda.saldo_pendiente, D('0'))
        self.assertEqual(self.tarjeta_deuda.disponible, D('20000'))

    def test_compra_con_tarjeta_aumenta_deuda(self):
        tx(self.user, 'GASTO', 1500, origen=self.tarjeta)
        self.tarjeta_deuda.refresh_from_db()
        self.assertEqual(self.tarjeta_deuda.saldo_pendiente, D('1500'))
        self.assertEqual(self.tarjeta_deuda.disponible, D('18500'))
        self.assertEqual(self.tarjeta_deuda.total_gastado, D('1500'))

    def test_pago_de_tarjeta_es_transferencia_y_reduce_deuda(self):
        tx(self.user, 'GASTO', 1500, origen=self.tarjeta)
        tx(self.user, 'TRANSFERENCIA', 1000, origen=self.debito, destino=self.tarjeta)
        self.assertEqual(self.tarjeta.saldo(), D('500'))
        self.assertEqual(self.debito.saldo(), D('0'))
        # el pago NO es gasto: el gasto ya se registró al comprar
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 10)
        self.assertEqual(bal['gastos'], D('1500'))
        self.assertEqual(bal['gastos_tarjeta'], D('1500'))
        self.assertEqual(bal['pagos_deuda'], D('1000'))

    def test_cuenta_credito_desde_gestionar_cuentas_crea_deuda(self):
        self.client.login(username='mau', password='x')
        self.client.post(reverse('gestionar_cuentas'), {
            'nombre': 'Tarjeta Banamex', 'terminacion': '1234', 'tipo': 'CREDITO', 'saldo_actual': '2500'})
        cuenta = Cuenta.objects.get(propietario=self.user, nombre='Tarjeta Banamex')
        self.assertEqual(cuenta.saldo(), D('2500'))
        self.assertTrue(Deuda.objects.filter(cuenta=cuenta, tipo_deuda='TARJETA_CREDITO').exists())

    def test_borrar_deuda_borra_su_cuenta(self):
        cuenta_id = self.tarjeta.id
        self.tarjeta_deuda.delete()
        self.assertFalse(Cuenta.objects.filter(id=cuenta_id).exists())


class PrestamoTest(BaseLibro):

    def setUp(self):
        super().setUp()
        self.prestamo = Deuda.objects.create(
            propietario=self.user, nombre='Crédito Coche', tipo_deuda='PRESTAMO',
            monto_total=D('100000'), tasa_interes=D('12'), plazo_meses=12)
        for i in range(1, 4):
            PagoAmortizacion.objects.create(
                deuda=self.prestamo, numero_cuota=i, fecha_vencimiento=date(2026, 10 + i - 1, 15),
                capital=D('8000'), interes=D('1000'), iva=D('160'), saldo_insoluto=D('100000') - D('8000') * i)

    def test_prestamo_nace_con_deuda_igual_al_monto(self):
        self.assertEqual(self.prestamo.cuenta.tipo, 'PRESTAMO')
        self.assertEqual(self.prestamo.saldo_pendiente, D('100000'))

    def test_pago_mensualidad_separa_capital_e_interes(self):
        pago = tx(self.user, 'PAGO_MENSUALIDAD', 9160, origen=self.debito, destino=self.prestamo.cuenta)
        pago.refresh_from_db()
        self.assertEqual(pago.monto_interes, D('1160'))
        self.assertEqual(pago.monto_capital, D('8000'))
        # la cuota quedó pagada y ligada
        cuota = PagoAmortizacion.objects.get(numero_cuota=1)
        self.assertTrue(cuota.pagado)
        self.assertEqual(cuota.transaccion_pago, pago)
        # el pasivo baja solo por el capital; la cuenta de débito baja por todo el pago
        self.assertEqual(self.prestamo.cuenta.saldo(), D('92000'))
        self.assertEqual(self.debito.saldo(), D('1000') - D('9160'))
        # en resultados solo el interés es gasto
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 10)
        self.assertEqual(bal['intereses'], D('1160'))
        self.assertEqual(bal['gastos'], D('1160'))
        self.assertEqual(bal['abonos_capital'], D('8000'))
        self.assertEqual(bal['pagos_deuda'], D('9160'))

    def test_borrar_pago_libera_la_cuota(self):
        pago = tx(self.user, 'PAGO_MENSUALIDAD', 9160, origen=self.debito, destino=self.prestamo.cuenta)
        pago.delete()
        cuota = PagoAmortizacion.objects.get(numero_cuota=1)
        self.assertFalse(cuota.pagado)
        self.assertIsNone(cuota.transaccion_pago)
        self.assertEqual(self.prestamo.cuenta.saldo(), D('100000'))

    def test_pago_capital_es_todo_capital(self):
        tx(self.user, 'PAGO_CAPITAL', 5000, origen=self.debito, destino=self.prestamo.cuenta)
        self.assertEqual(self.prestamo.cuenta.saldo(), D('95000'))
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 10)
        self.assertEqual(bal['gastos'], D('0'))

    def test_pago_a_tarjeta_como_mensualidad_es_invalido(self):
        mov = registro_transacciones(propietario=self.user, fecha=date(2026, 10, 1), descripcion='x', categoria='x',
                                     monto=D('100'), tipo='PAGO_MENSUALIDAD', origen=self.debito, destino=self.tarjeta)
        with self.assertRaises(ValidationError):
            mov.clean()


class DashboardCuadraTest(BaseLibro):
    """La tarjeta "Gastos" del dashboard debe ser la suma exacta de la gráfica por categoría."""

    def setUp(self):
        super().setUp()
        tx(self.user, 'INGRESO', 15000, destino=self.debito, categoria='Sueldo')
        tx(self.user, 'GASTO', 2000, origen=self.debito, categoria='Comida')
        tx(self.user, 'GASTO', 3000, origen=self.tarjeta, categoria='Ropa')        # con tarjeta
        tx(self.user, 'GASTO', 500, origen=self.efectivo, categoria='Comida')
        tx(self.user, 'TRANSFERENCIA', 3000, origen=self.debito, destino=self.tarjeta)   # pago tarjeta
        tx(self.user, 'TRANSFERENCIA', 2000, origen=self.debito, destino=self.ahorro)    # ahorro
        tx(self.user, 'GASTO', 999, origen=self.debito, fecha=date(2026, 9, 5), categoria='Otro mes')

    def test_gastos_incluyen_tarjeta_y_cuadran_con_categorias(self):
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 10)
        self.assertEqual(bal['ingresos'], D('15000'))
        self.assertEqual(bal['gastos'], D('5500'))
        self.assertEqual(bal['resultado'], D('9500'))
        self.assertEqual(bal['ahorro_neto'], D('2000'))
        self.assertEqual(bal['pagos_deuda'], D('3000'))
        por_cat = registro_transacciones.objects.gastos_por_categoria(self.user, 2026, 10)
        self.assertEqual(sum(f['total'] for f in por_cat), bal['gastos'])
        self.assertEqual({f['categoria']: f['total'] for f in por_cat}, {'Ropa': D('3000'), 'Comida': D('2500')})

    def test_vista_dashboard_y_apis(self):
        self.client.login(username='mau', password='x')
        r = self.client.get(reverse('dashboard') + '?year=2026&month=10')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['gastos'], D('5500'))
        self.assertEqual(r.context['ingresos'], D('15000'))
        self.assertEqual(r.context['balance'], D('9500'))
        # saldos reales al cierre del mes (incluye el gasto de septiembre):
        # débito = 1000 + 15000 - 2000 - 3000 - 2000 - 999 = 8001 ; efectivo = -500
        self.assertEqual(r.context['disponible_banco'], D('7501'))
        self.assertEqual(r.context['ahorro'], D('2000'))
        self.assertEqual(r.context['deuda_total'], D('0'))      # 3000 comprado - 3000 pagado
        self.assertEqual(r.context['total_pagado_deudas'], D('3000'))

        r = self.client.get(reverse('api_datos_gastos') + '?year=2026&month=10')
        self.assertEqual(sum(D(str(x)) for x in r.json()['data']), D('5500'))

        # Tarjetas de arriba = cifras globales del mes (no el saldo de la cuenta del carrusel)
        r = self.client.get(reverse('dashboard') + '?year=2026&month=10')
        metricas = r.context['metricas']
        self.assertEqual(metricas['balance']['total'], '9,500.00')
        self.assertEqual(metricas['ingresos']['total'], '15,000.00')
        self.assertEqual(metricas['gastos']['total'], '5,500.00')
        # el saldo de cada cuenta se muestra en el widget "Mis tarjetas"
        bbva = next(t for t in r.context['tarjetas_list'] if t['nombre'] == 'BBVA')
        self.assertEqual(bbva['saldo'], '$8,001.00')


class FormularioTest(BaseLibro):

    def test_ingreso_requiere_destino(self):
        form = TransaccionesForm({'fecha': '2026-10-01', 'descripcion': 'x', 'categoria': 'x', 'monto': '10',
                                  'tipo': 'INGRESO'}, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('destino', form.errors)

    def test_ingreso_capturado_en_origen_se_corrige(self):
        form = TransaccionesForm({'fecha': '2026-10-01', 'descripcion': 'x', 'categoria': 'x', 'monto': '10',
                                  'tipo': 'INGRESO', 'origen': self.debito.id}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        mov = form.save(commit=False)
        mov.propietario = self.user
        mov.save()
        self.assertEqual(mov.destino, self.debito)
        self.assertIsNone(mov.origen)

    def test_gasto_con_tarjeta_valido(self):
        form = TransaccionesForm({'fecha': '2026-10-01', 'descripcion': 'x', 'categoria': 'x', 'monto': '10',
                                  'tipo': 'GASTO', 'origen': self.tarjeta.id}, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_no_se_pueden_usar_cuentas_de_otro_usuario(self):
        otro = User.objects.create_user('otro', password='x')
        ajena = Cuenta.objects.create(propietario=otro, nombre='Ajena', tipo='DEBITO')
        form = TransaccionesForm({'fecha': '2026-10-01', 'descripcion': 'x', 'categoria': 'x', 'monto': '10',
                                  'tipo': 'GASTO', 'origen': ajena.id}, user=self.user)
        self.assertFalse(form.is_valid())


class MigracionDatosTest(TestCase):
    """Simula el estado anterior (nombres de texto, saldo mutable) y corre la migración de datos."""

    def setUp(self):
        self.user = User.objects.create_user('legacy', password='x')
        self.bbva = Cuenta.objects.create(propietario=self.user, nombre='BBVA', tipo='DEBITO')
        # tarjeta dada de alta como Cuenta CREDITO y como Deuda (sin ligar), como en el sistema viejo
        Cuenta.objects.create(propietario=self.user, nombre='Tarjeta Nu', tipo='CREDITO')
        self.deuda_tc = Deuda(propietario=self.user, nombre='Tarjeta Nu', tipo_deuda='TARJETA_CREDITO',
                              monto_total=D('10000'), tasa_interes=D('50'), plazo_meses=1)
        # saldo_legado = crédito DISPONIBLE en el sistema viejo (límite 10000 - 1500 gastados + 500 pagados)
        self.deuda_tc.saldo_legado = D('9000')
        self.deuda_tc.save()
        self.prestamo = Deuda(propietario=self.user, nombre='Crédito Coche', tipo_deuda='PRESTAMO',
                              monto_total=D('50000'), tasa_interes=D('12'), plazo_meses=12)
        self.prestamo.saldo_legado = D('46000')   # lo que se debe
        self.prestamo.save()

        def legacy(tipo, monto, origen, destino, fecha=date(2026, 9, 1), deuda=None):
            m = registro_transacciones(propietario=self.user, fecha=fecha, descripcion=tipo, categoria='x',
                                       monto=D(str(monto)), tipo=tipo, cuenta_origen=origen, cuenta_destino=destino,
                                       deuda_asociada=deuda)
            # bulk-style: sin normalizar (simula filas viejas sin FK)
            registro_transacciones.objects.bulk_create([m])
            return registro_transacciones.objects.latest('id')

        legacy('INGRESO', 8000, 'BBVA', 'Sin Cuenta')            # en el viejo, origen = cuenta que recibe
        legacy('GASTO', 700, 'BBVA', 'Sin Cuenta')
        legacy('GASTO', 1500, 'Tarjeta Nu', 'N/A')                 # compra con tarjeta
        legacy('TRANSFERENCIA', 500, 'BBVA', 'Tarjeta Nu')         # pago de tarjeta
        legacy('PAGO_MENSUALIDAD', 5000, 'BBVA', 'Crédito Coche', deuda=self.prestamo)
        legacy('GASTO', 100, 'Efectivo Quincena', 'N/A')           # nombre que no existe en el catálogo

    def test_migracion_liga_cuentas_y_concilia(self):
        reporte = _libro_mayor.migrar_a_libro_mayor(apps, verbose=False)

        self.deuda_tc.refresh_from_db()
        self.prestamo.refresh_from_db()
        tc = self.deuda_tc.cuenta
        pr = self.prestamo.cuenta
        self.assertEqual(tc.nombre, 'Tarjeta Nu')
        self.assertEqual(tc.tipo, 'CREDITO')
        self.assertEqual(pr.tipo, 'PRESTAMO')

        # semántica unificada
        ingreso = registro_transacciones.objects.get(tipo='INGRESO')
        self.assertEqual(ingreso.destino, self.bbva)
        self.assertIsNone(ingreso.origen)
        compra = registro_transacciones.objects.get(tipo='GASTO', monto=D('1500'))
        self.assertEqual(compra.origen, tc)
        self.assertEqual(compra.deuda_asociada, self.deuda_tc)
        pago_tc = registro_transacciones.objects.get(tipo='TRANSFERENCIA')
        self.assertEqual((pago_tc.origen, pago_tc.destino), (self.bbva, tc))
        pago_pr = registro_transacciones.objects.get(tipo='PAGO_MENSUALIDAD')
        self.assertEqual((pago_pr.origen, pago_pr.destino), (self.bbva, pr))

        # conciliación: el saldo derivado coincide con la deuda real del sistema viejo
        self.assertEqual(tc.saldo(), D('1000'))      # 10000 límite - 9000 disponible
        self.assertEqual(pr.saldo(), D('46000'))
        self.assertEqual(tc.saldo_inicial, D('0'))   # 1500 - 500 = 1000 ya explicado por movimientos
        self.assertEqual(pr.saldo_inicial, D('51000'))  # 46000 + 5000 pagado sin interés conocido

        # nombre no reconocido queda reportado y sin cuenta
        self.assertIn('Efectivo Quincena', reporte['nombres_sin_cuenta'])
        huerfano = registro_transacciones.objects.get(monto=D('100'))
        self.assertIsNone(huerfano.origen)

        # débito: 8000 - 700 - 500 - 5000 = 1800
        self.assertEqual(self.bbva.saldo(), D('1800'))


class PantallasTest(BaseLibro):
    """Humo: todas las pantallas que tocan el libro mayor renderizan sin error."""

    def setUp(self):
        super().setUp()
        self.client.login(username='mau', password='x')
        self.prestamo = Deuda.objects.create(
            propietario=self.user, nombre='Crédito Coche', tipo_deuda='PRESTAMO',
            monto_total=D('100000'), tasa_interes=D('12'), plazo_meses=12)
        self.mov = tx(self.user, 'GASTO', 250, origen=self.tarjeta)
        tx(self.user, 'INGRESO', 5000, destino=self.debito)
        tx(self.user, 'TRANSFERENCIA', 100, origen=self.debito, destino=self.ahorro)

    def test_pantallas(self):
        urls = [
            reverse('dashboard'),
            reverse('lista_transacciones') + '?year=2026&month=10',
            reverse('crear_transacciones'),
            reverse('editar_transaccion', args=[self.mov.id]),
            reverse('gestionar_cuentas'),
            reverse('editar_cuenta', args=[self.debito.id]),
            reverse('lista_deudas'),
            reverse('crear_deuda'),
            reverse('editar_deuda', args=[self.prestamo.id]),
            reverse('detalle_deuda', args=[self.prestamo.id]),
            reverse('revisar_tickets'),
            reverse('api_datos_presupuesto'),
            reverse('api_datos_gastos') + '?tipo=INGRESO',
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)

    def test_crear_transaccion_por_formulario(self):
        r = self.client.post(reverse('crear_transacciones'), {
            'fecha': '2026-10-20', 'descripcion': 'Super', 'categoria': 'Comida', 'monto': '320.50',
            'tipo': 'GASTO', 'origen': self.tarjeta.id, 'destino': '', 'monto_interes': ''})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.tarjeta.saldo(), D('570.50'))

    def test_editar_cuenta_concilia_saldo(self):
        r = self.client.post(reverse('editar_cuenta', args=[self.debito.id]), {
            'nombre': 'BBVA', 'terminacion': '', 'tipo': 'DEBITO', 'saldo_actual': '7777'})
        self.assertEqual(r.status_code, 302)
        self.debito.refresh_from_db()
        self.assertEqual(self.debito.saldo(), D('7777'))

    def test_editar_deuda_concilia_lo_que_debes(self):
        r = self.client.post(reverse('editar_deuda', args=[self.tarjeta_deuda.id]), {
            'nombre': 'Tarjeta Nu', 'tipo_deuda': 'TARJETA_CREDITO', 'monto_total': '20000',
            'tasa_interes': '60', 'plazo_meses': '1', 'fecha_adquisicion': '2026-01-01',
            'dia_corte': '6', 'dia_pago': '26', 'saldo_actual': '1234.56'})
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        self.tarjeta_deuda.refresh_from_db()
        self.assertEqual(self.tarjeta_deuda.saldo_pendiente, D('1234.56'))


class ComandoConciliarTest(BaseLibro):

    def test_reporte_de_todos_y_por_usuario(self):
        from io import StringIO
        from django.core.management import call_command
        otro = User.objects.create_user('otro', password='x')
        Cuenta.objects.create(propietario=otro, nombre='Caja', tipo='EFECTIVO', saldo_inicial=D('50'))
        out = StringIO()
        call_command('conciliar_saldos', stdout=out)
        texto = out.getvalue()
        self.assertIn('mau', texto)
        self.assertIn('otro', texto)
        out = StringIO()
        call_command('conciliar_saldos', '--usuario', 'mau', '--set', 'BBVA=4321', stdout=out)
        self.debito.refresh_from_db()
        self.assertEqual(self.debito.saldo(), D('4321'))
        with self.assertRaises(Exception):
            call_command('conciliar_saldos', '--set', 'BBVA=1', stdout=StringIO())


class TicketsUnClicTest(BaseLibro):
    """La revisión de tickets llega pre-llenada y se aprueba sin capturar nada."""

    def _ticket(self, **datos):
        from .models import TransaccionPendiente
        base = {'fecha': '2026-10-05', 'total': 4888.0, 'tipo_documento': 'TRANSFERENCIA',
                'tipo_movimiento': 'TRANSFERENCIA', 'descripcion_corta': 'Renta', 'cuenta_destino_sugerida': 'N/A'}
        base.update(datos)
        return TransaccionPendiente.objects.create(propietario=self.user, datos_json=base)

    def test_sugerencia_desde_historial(self):
        from .categorias import Sugeridor
        tx(self.user, 'GASTO', 4888, origen=self.efectivo, categoria='Alquiler', fecha=date(2026, 9, 5)).__class__.objects.filter(
            descripcion__startswith='GASTO').update(descripcion='RENTA')
        sug = Sugeridor(self.user).sugerir(self._ticket().datos_json)
        self.assertEqual(sug['origen'], 'Efectivo')      # de la última vez, no la principal
        self.assertEqual(sug['categoria'], 'Alquiler')
        self.assertEqual(sug['tipo'], 'GASTO')           # SPEI a un tercero = gasto
        self.assertEqual(sug['fuente'], 'historial')

    def test_sugerencia_cuenta_principal_y_terminacion(self):
        from .categorias import Sugeridor
        self.debito.es_principal = True
        self.debito.save()
        sug = Sugeridor(self.user).sugerir(self._ticket().datos_json)
        self.assertEqual(sug['origen'], 'BBVA')
        self.assertEqual(sug['fuente'], 'principal')
        # la IA leyó la terminación de la tarjeta en el ticket
        self.tarjeta.terminacion = '1002'
        self.tarjeta.save()
        sug = Sugeridor(self.user).sugerir(self._ticket(tipo_movimiento='GASTO', cuenta_origen_sugerida='Tarjeta **1002').datos_json)
        self.assertEqual(sug['origen'], 'Tarjeta Nu')

    def test_pantalla_y_aprobacion_sin_capturar_nada(self):
        self.debito.es_principal = True
        self.debito.save()
        ticket = self._ticket()
        self.client.login(username='mau', password='x')
        r = self.client.get(reverse('revisar_tickets'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['tickets'][0].sug['origen'], 'BBVA')
        # Aprobar todos mandando solo lo que el formulario ya traía (sin elegir cuenta ni categoría)
        r = self.client.post(reverse('aprobar_todos_tickets'), {
            f'cuenta_origen_{ticket.id}': '', f'categoria_{ticket.id}': '', f'tipo_{ticket.id}': 'TRANSFERENCIA',
            f'cuenta_destino_{ticket.id}': 'N/A'})
        self.assertEqual(r.status_code, 302)
        mov = registro_transacciones.objects.get(descripcion='RENTA')
        self.assertEqual(mov.tipo, 'GASTO')
        self.assertEqual(mov.origen, self.debito)
        self.assertEqual(mov.categoria, 'Otro')
        self.assertEqual(self.debito.saldo(), D('1000') - D('4888'))

    def test_transferencia_a_prestamo_se_vuelve_mensualidad(self):
        prestamo = Deuda.objects.create(propietario=self.user, nombre='Crédito Coche', tipo_deuda='PRESTAMO',
                                        monto_total=D('100000'), tasa_interes=D('12'), plazo_meses=12)
        PagoAmortizacion.objects.create(deuda=prestamo, numero_cuota=1, fecha_vencimiento=date(2026, 10, 15),
                                        capital=D('4000'), interes=D('800'), iva=D('128'), saldo_insoluto=D('96000'))
        ticket = self._ticket(descripcion_corta='Pago Digitt', total=4928.0, cuenta_destino_sugerida='Crédito Coche')
        self.client.login(username='mau', password='x')
        r = self.client.post(reverse('aprobar_ticket', args=[ticket.id]), {
            f'cuenta_origen_{ticket.id}': 'BBVA', f'categoria_{ticket.id}': 'Deudas',
            f'tipo_{ticket.id}': 'TRANSFERENCIA', f'cuenta_destino_{ticket.id}': 'Crédito Coche'})
        self.assertEqual(r.status_code, 302)
        mov = registro_transacciones.objects.get(descripcion='PAGO DIGITT')
        self.assertEqual(mov.tipo, 'PAGO_MENSUALIDAD')
        self.assertEqual(mov.monto_interes, D('928'))
        self.assertEqual(prestamo.cuenta.saldo(), D('96000'))
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 10)
        self.assertEqual(bal['gastos'], D('928'))


class FechasTest(TestCase):
    def test_fecha_iso_no_cambia_mes_por_dia(self):
        from .utils import parse_date_safely
        self.assertEqual(parse_date_safely('2026-10-05'), date(2026, 10, 5))
        self.assertEqual(parse_date_safely('05/10/2026'), date(2026, 10, 5))
        self.assertEqual(parse_date_safely('2026-10-05T12:30:00'), date(2026, 10, 5))


class AhorroNoEsGastoTest(BaseLibro):

    def _ticket(self, **datos):
        from .models import TransaccionPendiente
        base = {'fecha': '2026-07-03', 'total': 30468.0, 'tipo_documento': 'TRANSFERENCIA',
                'tipo_movimiento': 'TRANSFERENCIA', 'descripcion_corta': 'Ahorro', 'cuenta_destino_sugerida': 'N/A'}
        base.update(datos)
        return TransaccionPendiente.objects.create(propietario=self.user, datos_json=base)

    def test_sugerencia_ahorro_con_cuenta_existente(self):
        from .categorias import Sugeridor
        sug = Sugeridor(self.user).sugerir(self._ticket().datos_json)
        self.assertEqual(sug['tipo'], 'TRANSFERENCIA')
        self.assertEqual(sug['destino'], 'Ahorro Nu')
        self.assertEqual(sug['categoria'], 'Ahorro')

    def test_sugerencia_ahorro_sin_cuenta_de_ahorro(self):
        from .categorias import Sugeridor, SENTINELA_NUEVA_AHORRO
        self.ahorro.delete()
        sug = Sugeridor(self.user).sugerir(self._ticket().datos_json)
        self.assertEqual(sug['tipo'], 'TRANSFERENCIA')
        self.assertEqual(sug['destino'], SENTINELA_NUEVA_AHORRO)
        self.assertIn('Cuenta Ahorro', sug['aviso'])

    def test_sugerencia_transferencia_a_cuenta_mencionada(self):
        from .categorias import Sugeridor
        nu = Cuenta.objects.create(propietario=self.user, nombre='NU (Debito)', tipo='DEBITO')
        sug = Sugeridor(self.user).sugerir(self._ticket(descripcion_corta='Mauricio nu').datos_json)
        self.assertEqual(sug['tipo'], 'TRANSFERENCIA')
        self.assertEqual(sug['destino'], 'NU (Debito)')      # sin pista, se prefiere la cuenta de activo
        self.assertEqual(sug['categoria'], 'Transferencia')
        # si además existe una tarjeta "Nu" y la IA dijo "Deudas", se prefiere el pasivo
        self.assertEqual(Sugeridor(self.user).sugerir(self._ticket(descripcion_corta='Pago nu', categoria_sugerida='Deudas').datos_json)['destino'], 'Tarjeta Nu')
        nu.delete()

    def test_aprobar_ahorro_crea_cuenta_y_no_es_gasto(self):
        self.ahorro.delete()
        ticket = self._ticket()
        self.client.login(username='mau', password='x')
        r = self.client.post(reverse('aprobar_ticket', args=[ticket.id]), {
            f'cuenta_origen_{ticket.id}': 'BBVA', f'categoria_{ticket.id}': 'Ahorro',
            f'tipo_{ticket.id}': 'GASTO', f'cuenta_destino_{ticket.id}': 'N/A'})
        self.assertEqual(r.status_code, 302)
        mov = registro_transacciones.objects.get(descripcion='AHORRO')
        self.assertEqual(mov.tipo, 'TRANSFERENCIA')
        self.assertEqual(mov.destino.tipo, 'AHORRO')
        self.assertEqual(mov.destino.nombre, 'Cuenta Ahorro')
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 7)
        self.assertEqual(bal['gastos'], D('0'))
        self.assertEqual(bal['ahorro_neto'], D('30468'))
        resumen = Cuenta.objects.resumen_balance(self.user)
        self.assertEqual(resumen['patrimonio'], D('1000'))   # el patrimonio no cambia al ahorrar

    def test_migracion_0025_reclasifica_ahorros_viejos(self):
        from .migrations import _libro_mayor
        self.ahorro.delete()
        viejo = tx(self.user, 'GASTO', 5083, origen=self.debito, categoria='Ahorro', fecha=date(2026, 7, 4))
        normal = tx(self.user, 'GASTO', 100, origen=self.debito, categoria='Comida', fecha=date(2026, 7, 4))
        resumen = _libro_mayor.migrar_ahorros(apps, verbose=False)
        viejo.refresh_from_db(); normal.refresh_from_db()
        self.assertEqual(viejo.tipo, 'TRANSFERENCIA')
        self.assertEqual(viejo.destino.tipo, 'AHORRO')
        self.assertEqual(normal.tipo, 'GASTO')
        self.assertEqual(resumen[0][2], 1)
        bal = registro_transacciones.objects.balance_dashboard(self.user, 2026, 7)
        self.assertEqual(bal['gastos'], D('100'))
        self.assertEqual(bal['ahorro_neto'], D('5083'))


class ResumenTest(BaseLibro):

    def setUp(self):
        super().setUp()
        self.client.login(username='mau', password='x')
        # Septiembre
        tx(self.user, 'INGRESO', 38752, destino=self.debito, categoria='Sueldo', fecha=date(2026, 9, 15))
        tx(self.user, 'GASTO', 6841, origen=self.debito, categoria='Comidas fuera', fecha=date(2026, 9, 10))
        tx(self.user, 'GASTO', 1800, origen=self.debito, categoria='Gasolina', fecha=date(2026, 9, 12))
        tx(self.user, 'TRANSFERENCIA', 2500, origen=self.debito, destino=self.ahorro, fecha=date(2026, 9, 16))
        # Octubre
        tx(self.user, 'INGRESO', 38810, destino=self.debito, categoria='Sueldo', fecha=date(2026, 10, 15))
        tx(self.user, 'GASTO', 5249, origen=self.debito, categoria='Comidas fuera', fecha=date(2026, 10, 10))
        tx(self.user, 'GASTO', 1000, origen=self.debito, categoria='Gasolina', fecha=date(2026, 10, 12))
        tx(self.user, 'GASTO', 3000, origen=self.tarjeta, categoria='Ropa', fecha=date(2026, 10, 3))
        tx(self.user, 'TRANSFERENCIA', 1000, origen=self.debito, destino=self.tarjeta, fecha=date(2026, 10, 20))

    def test_estado_de_resultados_con_variaciones(self):
        r = self.client.get(reverse('resumen') + '?year=2026&month=10')
        self.assertEqual(r.status_code, 200)
        filas = {f['nombre']: f for f in r.context['filas_gastos']}
        comidas = filas['Comidas fuera']
        self.assertEqual((comidas['anterior'], comidas['actual'], comidas['dif']), (D('6841'), D('5249'), D('-1592')))
        self.assertTrue(comidas['revisar'])           # -1592 y -23%: supera $500 y 20%
        self.assertTrue(comidas['favorable'])
        gasolina = filas['Gasolina']
        self.assertTrue(gasolina['revisar'])          # -800 y -44%
        ropa = filas['Ropa']
        self.assertTrue(ropa['revisar'])              # antes era 0
        self.assertIsNone(ropa['pct'])
        total = filas['Total gastos']
        self.assertEqual(total['actual'], D('9249'))  # incluye los 3000 con tarjeta
        self.assertEqual(r.context['fila_resultado']['actual'], D('38810') - D('9249'))
        # umbrales personalizados: con $2000 solo Comidas y Ropa superan
        r = self.client.get(reverse('resumen') + '?year=2026&month=10&umbral=2000&pct=20')
        filas = {f['nombre']: f for f in r.context['filas_gastos']}
        self.assertFalse(filas['Gasolina']['revisar'])
        self.assertTrue(filas['Comidas fuera']['revisar'] is False or filas['Comidas fuera']['dif'] == D('-1592'))

    def test_entre_cuentas_cuadre_y_notas(self):
        r = self.client.get(reverse('resumen') + '?year=2026&month=10')
        entre = {e['cuenta'].nombre: e for e in r.context['entre_cuentas']}
        self.assertEqual(entre['Tarjeta Nu']['actual'], D('1000'))     # pago de tarjeta: recibió
        self.assertEqual(entre['BBVA']['actual'], D('-1000'))          # débito: envió
        self.assertEqual(entre['Ahorro Nu']['anterior'], D('2500'))
        cuadre = {q['cuenta'].nombre: q for q in r.context['cuadre']}
        bbva = cuadre['BBVA']
        self.assertEqual(bbva['inicial'], D('1000') + D('38752') - D('6841') - D('1800') - D('2500'))
        self.assertEqual(bbva['final'], bbva['inicial'] + bbva['entradas'] - bbva['salidas'])
        tarjeta = cuadre['Tarjeta Nu']
        self.assertEqual((tarjeta['inicial'], tarjeta['salidas'], tarjeta['entradas'], tarjeta['final']), (D('0'), D('3000'), D('1000'), D('2000')))
        notas = ' '.join(r.context['notas'])
        self.assertIn('Comidas fuera', notas)
        self.assertIn('Captura el saldo', notas)

    def test_conciliacion_guarda_y_cuadra(self):
        url = reverse('resumen') + '?year=2026&month=10'
        r = self.client.get(url)
        registro_bbva = {c['cuenta'].id: c for c in r.context['conciliacion']}[self.debito.id]['registro']
        # el banco dice lo mismo que el registro -> cuadra; la tarjeta dice 2500 -> diferencia +500
        r = self.client.post(url, {f'saldo_banco_{self.debito.id}': f'{registro_bbva:.2f}',
                                   f'saldo_banco_{self.tarjeta.id}': '2,500.00'})
        self.assertEqual(r.status_code, 302)
        r = self.client.get(url)
        conc = {c['cuenta'].id: c for c in r.context['conciliacion']}
        self.assertTrue(conc[self.debito.id]['cuadra'])
        self.assertFalse(conc[self.tarjeta.id]['cuadra'])
        self.assertEqual(conc[self.tarjeta.id]['diferencia'], D('500'))
        self.assertIn('Tarjeta Nu: diferencia +$500.00 (según el banco debes más', ' '.join(r.context['notas']))
        # fijar saldo inicial con el valor del banco: ahora cuadra y el saldo de hoy también cambió
        r = self.client.post(url, {f'saldo_banco_{self.tarjeta.id}': '2500', f'fijar_inicial_{self.tarjeta.id}': '1'})
        r = self.client.get(url)
        conc = {c['cuenta'].id: c for c in r.context['conciliacion']}
        self.assertTrue(conc[self.tarjeta.id]['cuadra'])
        self.tarjeta.refresh_from_db()
        self.assertEqual(self.tarjeta.saldo_inicial, D('500'))
        # ya conciliada en un mes anterior -> en noviembre no se ofrece "fijar inicial"
        r = self.client.get(reverse('resumen') + '?year=2026&month=11')
        conc = {c['cuenta'].id: c for c in r.context['conciliacion']}
        self.assertFalse(conc[self.tarjeta.id]['puede_fijar_inicial'])
        self.assertTrue(conc[self.efectivo.id]['puede_fijar_inicial'])


class CapturaDelBancoEsIngresoTest(BaseLibro):
    """Una captura de la app del banco se lee como INGRESO con el monto, en la fila normal."""

    def _ticket(self, **datos):
        from .models import TransaccionPendiente
        base = {'fecha': '2026-10-28', 'total': 19413.28, 'tipo_documento': 'CAPTURA_BANCO', 'tipo_movimiento': 'INGRESO',
                'descripcion_corta': 'Depósito', 'categoria_sugerida': 'Nomina', 'cuenta_origen_sugerida': 'BBVA'}
        base.update(datos)
        return TransaccionPendiente.objects.create(propietario=self.user, datos_json=base)

    def test_sugerencia_y_aprobacion_como_ingreso(self):
        from .categorias import Sugeridor
        ticket = self._ticket()
        sug = Sugeridor(self.user).sugerir(ticket.datos_json)
        self.assertEqual((sug['tipo'], sug['origen'], sug['categoria']), ('INGRESO', 'BBVA', 'Nomina'))
        self.client.login(username='mau', password='x')
        r = self.client.get(reverse('revisar_tickets'))
        self.assertEqual(r.context['tickets'][0].clase, 'MOVIMIENTO')
        self.assertContains(r, '$19413.28')
        r = self.client.post(reverse('aprobar_todos_tickets'), {
            f'cuenta_origen_{ticket.id}': 'BBVA', f'categoria_{ticket.id}': 'Nomina',
            f'tipo_{ticket.id}': 'INGRESO', f'cuenta_destino_{ticket.id}': 'N/A'})
        self.assertEqual(r.status_code, 302)
        mov = registro_transacciones.objects.get(descripcion='NÓMINA')   # 'Depósito' + categoría Nómina -> NÓMINA
        self.assertEqual((mov.tipo, mov.monto, mov.destino, mov.origen), ('INGRESO', D('19413.28'), self.debito, None))
        self.assertEqual(self.debito.saldo(), D('1000') + D('19413.28'))

    def test_sin_monto_se_escribe_en_la_fila(self):
        ticket = self._ticket(total=0.0, descripcion_corta='Consulta de saldo')
        self.client.login(username='mau', password='x')
        r = self.client.get(reverse('revisar_tickets'))
        self.assertEqual(r.context['tickets'][0].clase, 'SIN_MONTO')
        self.assertContains(r, f'name="monto_{ticket.id}"')
        # sin escribir monto no se registra nada
        self.client.post(reverse('aprobar_ticket', args=[ticket.id]), {
            f'cuenta_origen_{ticket.id}': 'BBVA', f'categoria_{ticket.id}': 'Nomina', f'tipo_{ticket.id}': 'INGRESO'})
        self.assertEqual(registro_transacciones.objects.count(), 0)
        # escribiendo el monto, sí
        self.client.post(reverse('aprobar_ticket', args=[ticket.id]), {
            f'cuenta_origen_{ticket.id}': 'BBVA', f'categoria_{ticket.id}': 'Nomina', f'tipo_{ticket.id}': 'INGRESO',
            f'monto_{ticket.id}': '19,413.28'})
        mov = registro_transacciones.objects.get()
        self.assertEqual((mov.tipo, mov.monto, mov.destino), ('INGRESO', D('19413.28'), self.debito))
        self.assertEqual(mov.descripcion, 'NÓMINA')   # ingreso de categoría Nómina con descripción genérica


class PagoDeDeudaDesdeTicketTest(BaseLibro):

    def test_gasto_deudas_que_menciona_el_prestamo(self):
        from .categorias import Sugeridor
        Deuda.objects.create(propietario=self.user, nombre='Digitt', tipo_deuda='PRESTAMO',
                             monto_total=D('15000'), tasa_interes=D('30'), plazo_meses=12)
        datos = {'fecha': '2026-06-12', 'total': 1800.0, 'tipo_movimiento': 'GASTO', 'tipo_documento': 'TRANSFERENCIA',
                 'descripcion_corta': 'Digitt001mensualidad', 'categoria_sugerida': 'Deudas', 'cuenta_destino_sugerida': 'N/A'}
        sug = Sugeridor(self.user).sugerir(datos)
        self.assertEqual(sug['tipo'], 'TRANSFERENCIA')
        self.assertEqual(sug['destino'], 'Digitt')
        # tarjeta que no está registrada: se queda como gasto
        datos['descripcion_corta'] = 'Deuda banamex'
        sug = Sugeridor(self.user).sugerir(datos)
        self.assertEqual(sug['tipo'], 'GASTO')
        self.assertEqual(sug['destino'], '')
