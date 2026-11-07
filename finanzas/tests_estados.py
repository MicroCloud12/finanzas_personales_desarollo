"""
Pruebas de los estados financieros del año (views/estados.py).

Correr:  python manage.py test finanzas.tests_estados
"""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Cuenta, Deuda, Presupuesto, registro_transacciones
from .views import estados

D = Decimal
HOY = date(2026, 11, 4)


def tx(user, tipo, monto, fecha, origen=None, destino=None, categoria='Varios', **extra):
    return registro_transacciones.objects.create(
        propietario=user, fecha=fecha, descripcion=f'{tipo} {monto}', categoria=categoria,
        monto=D(str(monto)), tipo=tipo, origen=origen, destino=destino, **extra)


class EstadosBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.debito = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO', saldo_inicial=D('10000'))
        self.ahorro = Cuenta.objects.create(propietario=self.user, nombre='Nu cajitas', tipo='AHORRO')
        self.tarjeta = Deuda.objects.create(
            propietario=self.user, nombre='AMEX', tipo_deuda='TARJETA_CREDITO',
            monto_total=D('20000'), tasa_interes=D('60'), plazo_meses=1).cuenta
        # Enero a marzo 2026, más un movimiento del año anterior
        tx(self.user, 'INGRESO', 20000, date(2025, 12, 15), destino=self.debito, categoria='Nomina')
        for mes in (1, 2, 3):
            tx(self.user, 'INGRESO', 20000, date(2026, mes, 15), destino=self.debito, categoria='Nomina')
            tx(self.user, 'GASTO', 9000, date(2026, mes, 1), origen=self.debito, categoria='Alquiler')
            tx(self.user, 'GASTO', 3000, date(2026, mes, 10), origen=self.debito, categoria='Comida')
            tx(self.user, 'TRANSFERENCIA', 2000, date(2026, mes, 16), origen=self.debito, destino=self.ahorro, categoria='Ahorro')
        tx(self.user, 'GASTO', 6000, date(2026, 3, 20), origen=self.tarjeta, categoria='Comida')  # marzo se dispara
        self.client.login(username='mau', password='x')

    def estado(self, **params):
        with mock.patch.object(estados, 'date', _FechaFija):
            return self.client.get(reverse('estado_resultados'), params).context

    def balance(self, **params):
        with mock.patch.object(estados, 'date', _FechaFija):
            return self.client.get(reverse('balance_general'), params).context


class _FechaFija(date):
    """date.today() fijo para que las pruebas no dependan del día en que corren."""
    @classmethod
    def today(cls):
        return HOY


class EstadoResultadosTest(EstadosBase):

    def test_columnas_hasta_el_mes_en_curso_y_promedio_de_cerrados(self):
        ctx = self.estado(year=2026)
        self.assertEqual([m['num'] for m in ctx['meses']], list(range(1, 12)))
        self.assertEqual(ctx['n_cerrados'], 10)          # noviembre (en curso) no cuenta
        self.assertEqual(ctx['total_ingresos'], D('60000'))
        self.assertEqual(ctx['total_gastos'], D('42000'))  # 3×12000 + 6000 con tarjeta
        self.assertEqual(ctx['resultado_anual'], D('18000'))
        self.assertEqual(ctx['promedio_gasto'], D('4200'))  # 42000 / 10 meses cerrados

    def test_fila_por_categoria_y_revisar_contra_el_promedio(self):
        ctx = self.estado(year=2026, umbral=500, pct=20)
        comida = next(f for f in ctx['filas_gastos'] if f['nombre'] == 'Comida')
        self.assertEqual(comida['total'], D('15000'))
        self.assertEqual([c['valor'] for c in comida['celdas'][:3]], [D('3000'), D('3000'), D('9000')])
        self.assertEqual(comida['promedio'], D('1500'))     # 15000 / 10 meses cerrados
        self.assertTrue(comida['celdas'][2]['revisar'])    # marzo: 9000 vs promedio 1500
        self.assertTrue(comida['celdas'][0]['revisar'])    # enero: 3000 vs 1500 = +1500 (≥500 y ≥20%)
        # abril: 0 vs 1500, pero la categoría solo aparece en 3 de 10 meses cerrados (esporádica): no se marca
        self.assertFalse(comida['celdas'][3]['revisar'])
        self.assertFalse(comida['celdas'][-1]['revisar'])  # el mes en curso nunca se marca
        self.assertFalse(comida['celdas'][0]['favorable']) # en gastos, subir es desfavorable
        alquiler = next(f for f in ctx['filas_gastos'] if f['nombre'] == 'Alquiler')
        self.assertEqual(alquiler['total'], D('27000'))
        self.assertEqual(ctx['filas_gastos'][-1]['nombre'], 'Total gastos')
        self.assertEqual(ctx['filas_gastos'][-1]['celdas'][2]['valor'], D('18000'))

    def test_presupuesto_recurrente_y_del_mes(self):
        Presupuesto.objects.create(propietario=self.user, categoria='comida', monto_presupuestado=D('3500'))
        Presupuesto.objects.create(propietario=self.user, categoria='Comida', monto_presupuestado=D('5000'),
                                   es_recurrente=False, mes=3, anio=2026)
        Presupuesto.objects.create(propietario=self.user, categoria='Transporte', monto_presupuestado=D('1000'))
        ctx = self.estado(year=2026)
        comida = next(f for f in ctx['filas_gastos'] if f['nombre'] == 'Comida')
        self.assertEqual(comida['celdas'][2]['presupuesto'], D('5000'))      # marzo: el específico manda
        self.assertEqual(comida['presupuesto'], D('3500') * 10 + D('5000'))  # 11 meses mostrados
        self.assertEqual(comida['dif_presupuesto'], D('15000') - comida['presupuesto'])
        transporte = next(f for f in ctx['filas_gastos'] if f['nombre'] == 'Transporte')
        self.assertEqual(transporte['total'], D('0'))                        # presupuestado sin gasto: aparece
        self.assertEqual(ctx['filas_gastos'][-1]['presupuesto'], D('4500') * 10 + D('6000'))
        # dif del total = solo categorías presupuestadas: comida (15000 - 40000) + transporte (0 - 11000)
        self.assertEqual(ctx['filas_gastos'][-1]['dif_presupuesto'], D('15000') - (D('3500') * 10 + D('5000')) - D('11000'))
        self.assertTrue(ctx['hay_presupuesto'])

    def test_anio_cerrado_muestra_doce_meses(self):
        ctx = self.estado(year=2025)
        self.assertEqual(len(ctx['meses']), 12)
        self.assertEqual(ctx['n_cerrados'], 12)
        self.assertEqual(ctx['total_ingresos'], D('20000'))

    def test_parametros_invalidos_redirigen(self):
        self.assertEqual(self.client.get(reverse('estado_resultados'), {'year': 'x'}).status_code, 302)


class BalanceGeneralTest(EstadosBase):

    def test_tres_cortes_y_comprobacion_del_anio(self):
        ctx = self.balance(fecha='2026-03-31')
        self.assertEqual(ctx['cortes'], ['Cierre 2025', 'Cierre Febrero 2026', 'Al 31/03/2026'])
        g = ctx['grupos']
        # Santander: 10000 + 20000 (dic) = 30000 al cierre 2025; luego +20000 -12000 -2000 por mes
        santander = g['grupos_activos'][0]['filas'][0]
        self.assertEqual(santander['valores'], [D('30000'), D('42000'), D('48000')])
        self.assertEqual(santander['dif_mes'], D('6000'))
        self.assertEqual(santander['dif_anio'], D('18000'))
        self.assertEqual(g['total_pasivos']['valores'][-1], D('6000'))       # compra con tarjeta
        self.assertEqual(g['patrimonio']['valores'], [D('30000'), D('46000'), D('48000')])
        # capital 2025 (30000) + resultado acumulado (60000 - 42000) = 48000 = capital hoy
        self.assertEqual(ctx['capital_ini'], D('30000'))
        self.assertEqual(ctx['acumulado']['resultado'], D('18000'))
        self.assertEqual(ctx['sin_explicar'], D('0'))
        self.assertTrue(ctx['cuadra'])

    def test_serie_mensual_cuadra_con_el_resultado_de_cada_mes(self):
        ctx = self.balance(fecha='2026-03-31')
        serie = ctx['serie']
        self.assertEqual([s['patrimonio'] for s in serie], [D('38000'), D('46000'), D('48000')])
        self.assertEqual([s['dif'] for s in serie], [D('8000'), D('8000'), D('2000')])
        self.assertEqual([s['sin_explicar'] for s in serie], [D('0')] * 3)
        self.assertEqual(ctx['grafica']['labels'], ['Dic 2025', 'Ene', 'Feb', 'Mar'])
        self.assertEqual(ctx['grafica']['patrimonio'], [30000.0, 38000.0, 46000.0, 48000.0])

    def test_ajuste_de_saldo_inicial_aparece_como_sin_explicar(self):
        self.debito.saldo_inicial = D('10500')   # 500 que no vinieron de ningún ingreso
        self.debito.save()
        ctx = self.balance(fecha='2026-03-31')
        # El saldo inicial afecta también el cierre 2025, así que el año sigue cuadrando...
        self.assertTrue(ctx['cuadra'])
        # ...pero un movimiento sin cuenta de contrapartida sí descuadra el mes
        tx(self.user, 'TRANSFERENCIA', 700, date(2026, 2, 5), origen=None, destino=self.debito, categoria='Transferencia')
        ctx = self.balance(fecha='2026-03-31')
        self.assertEqual(ctx['sin_explicar'], D('700'))
        self.assertFalse(ctx['cuadra'])
        self.assertEqual(ctx['serie'][1]['sin_explicar'], D('700'))

    def test_fecha_por_defecto_es_hoy_y_fecha_invalida_redirige(self):
        ctx = self.balance()
        self.assertEqual(ctx['fecha'], HOY)
        self.assertEqual(len(ctx['serie']), 11)
        self.assertEqual(self.client.get(reverse('balance_general'), {'fecha': '2026-13-01'}).status_code, 302)


class PantallasEstadosTest(EstadosBase):

    def test_pantallas_renderizan(self):
        for url in (reverse('estado_resultados'), reverse('balance_general'), reverse('resumen')):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
        r = self.client.get(reverse('resumen'), {'year': 2026, 'month': 3})
        self.assertNotContains(r, 'Balance general al')       # ya no vive en Resumen
        self.assertContains(r, 'ver balance general')
        r = self.client.get(reverse('estado_resultados'), {'year': 2026})
        self.assertContains(r, 'Total 2026')
        self.assertContains(r, 'Alquiler')
        r = self.client.get(reverse('balance_general'), {'fecha': '2026-03-31'})
        self.assertContains(r, 'Comprobación del año ✓')
        self.assertContains(r, 'grafica-patrimonio')
