"""
Pruebas del Presupuesto como plan de gastos fijos: próximo pago y cuánto apartar por quincena.

Correr:  python manage.py test finanzas.tests_presupuesto
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import PresupuestoForm
from .models import HistorialReciboServicio, Presupuesto, registro_transacciones
from .services.prediccion import Recibo, cadencia_dias, estimar_para_fecha, pagos_en_mes, prediccion_variable
from .views.presupuesto import estimacion, plan_quincenal, prediccion_mes, proxima_quincena, recibos_del_libro

D = Decimal
HOY = date(2026, 11, 19)


class QuincenaTest(TestCase):
    def test_proxima_nomina_es_el_13_o_el_28_siguiente(self):
        self.assertEqual(proxima_quincena(date(2026, 11, 19)), date(2026, 11, 28))
        self.assertEqual(proxima_quincena(date(2026, 11, 28)), date(2026, 12, 13))   # el día de nómina ya no cuenta
        self.assertEqual(proxima_quincena(date(2026, 12, 30)), date(2027, 1, 13))


class PlanQuincenalTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        crear = lambda **kw: Presupuesto.objects.create(propietario=self.user, **kw)
        self.renta = crear(categoria='Renta', monto_presupuestado=D('9777'), dia_pago=29)
        self.muchacha = crear(categoria='Muchacha', monto_presupuestado=D('1000'), dia_pago=25)
        self.luz = crear(categoria='Luz', monto_presupuestado=D('0'))
        for fecha, monto in [(date(2026, 7, 10), '900'), (date(2026, 9, 9), '1000'), (date(2026, 11, 9), '1100')]:
            HistorialReciboServicio.objects.create(propietario=self.user, presupuesto=self.luz, fecha_emision=fecha,
                                                   monto_total=D(monto), archivo_drive_id=f'luz-{fecha}')
        self.internet = crear(categoria='Internet', monto_presupuestado=D('599'), fecha_proximo_recibo=date(2026, 12, 5))
        self.tenencia = crear(categoria='Tenencia', monto_presupuestado=D('3000'), es_recurrente=False, mes=12, anio=2026,
                              dia_pago=20)

    def test_monto_fijo_usa_su_dia_de_pago(self):
        fecha, monto, paso, facturado = estimacion(self.renta, HOY)
        self.assertEqual((fecha, monto, paso, facturado), (date(2026, 11, 29), 9777.0, 30, False))

    def test_recibo_en_mano_es_el_proximo_pago(self):
        # El último recibo (9/11) aún no vence: sin fecha límite leída se asume emisión + 12 días.
        fecha, monto, paso, facturado = estimacion(self.luz, HOY)
        self.assertEqual((fecha, monto, paso, facturado), (date(2026, 11, 21), 1100.0, 61, True))
        self.luz.refresh_from_db()
        self.assertEqual(self.luz.monto_presupuestado, D('0'))      # no toca lo guardado (eso lo hace Predecir)

    def test_fecha_limite_leida_del_recibo_manda(self):
        ultimo = self.luz.historial_recibos.order_by('-fecha_emision').first()
        ultimo.datos_json = {'fecha_limite_pago': '2026-11-30'}
        ultimo.save()
        self.assertEqual(estimacion(self.luz, HOY)[:2], (date(2026, 11, 30), 1100.0))
        ultimo.datos_json = {'fecha_limite_pago': 'no dice'}        # basura de la IA: cae al +12 días
        ultimo.save()
        self.assertEqual(estimacion(self.luz, HOY)[0], date(2026, 11, 21))

    def test_recibo_ya_vencido_proyecta_el_siguiente_ciclo(self):
        fecha, monto, paso, facturado = estimacion(self.luz, date(2026, 12, 15))
        self.assertEqual((fecha, paso, facturado), (date(2027, 1, 21), 61, False))   # vence 21/11 + 61
        self.assertAlmostEqual(monto, 1200.0)                       # tendencia +100 por recibo

    def test_variable_sin_recibos_usa_lo_capturado(self):
        self.assertEqual(estimacion(self.internet, HOY), (date(2026, 12, 5), 599.0, 30, False))
        self.internet.fecha_proximo_recibo = date(2026, 11, 1)      # ya pasó: no se puede proyectar
        self.assertEqual(estimacion(self.internet, HOY)[0], None)

    def test_plan_reparte_cada_pago_en_sus_quincenas(self):
        plan = plan_quincenal(Presupuesto.objects.filter(propietario=self.user).order_by('id'), HOY)
        por = {f['p'].categoria: f for f in plan['filas']}
        self.assertEqual(por['Renta']['por_quincena'], 4888.5)             # mensual: mitad y mitad
        self.assertEqual(por['Luz']['por_quincena'], round(1100 * 15 / 61, 2))   # bimestral: en ~4 quincenas
        self.assertEqual(por['Internet']['por_quincena'], 299.5)
        self.assertEqual(por['Tenencia']['por_quincena'], 1000.0)          # 3,000 el 20/12: quedan 3 quincenas
        self.assertEqual(plan['proxima_nomina'], date(2026, 11, 28))
        self.assertTrue(por['Muchacha']['vence_antes'])                    # 25/11 cae antes de la nómina del 28
        self.assertTrue(por['Luz']['vence_antes'])                         # el recibo en mano vence el 21/11
        self.assertFalse(por['Renta']['vence_antes'])                      # 29/11 ya es con la siguiente
        self.assertEqual((plan['vence_antes'], plan['n_vencen']), (2100.0, 2))
        self.assertEqual(plan['total_quincena'], round(4888.5 + 500 + 1100 * 15 / 61 + 299.5 + 1000, 2))


class ProximoMesTest(TestCase):
    """Columna 'Próximo mes': lo que toca pagar de cada concepto el mes que entra (HOY es noviembre → diciembre)."""

    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        crear = lambda **kw: Presupuesto.objects.create(propietario=self.user, **kw)
        self.renta = crear(categoria='Renta', monto_presupuestado=D('9777'), dia_pago=29)
        self.luz = crear(categoria='Luz', monto_presupuestado=D('0'))
        for fecha, monto in [(date(2026, 7, 10), '900'), (date(2026, 9, 9), '1000'), (date(2026, 11, 9), '1100')]:
            HistorialReciboServicio.objects.create(propietario=self.user, presupuesto=self.luz, fecha_emision=fecha,
                                                   monto_total=D(monto), archivo_drive_id=f'luz-{fecha}')
        self.gas = crear(categoria='Gas', monto_presupuestado=D('0'))      # sin recibos: se apoya en los movimientos
        for fecha, desc, monto in [(date(2026, 9, 3), 'GAS', '560'), (date(2026, 10, 3), 'Gas natural', '580'),
                                   (date(2026, 11, 3), 'GAS', '598.87'), (date(2026, 11, 5), 'GASOLINA', '450')]:
            registro_transacciones.objects.create(propietario=self.user, fecha=fecha, descripcion=desc,
                                                  categoria='Servicios', monto=D(monto), tipo='GASTO')
        self.agua = crear(categoria='Agua', monto_presupuestado=D('300'))  # sin recibos ni movimientos
        self.tenencia = crear(categoria='Tenencia', monto_presupuestado=D('3000'), es_recurrente=False, mes=12, anio=2026, dia_pago=20)
        self.predial = crear(categoria='Predial', monto_presupuestado=D('2000'), es_recurrente=False, mes=2, anio=2027)

    def test_monto_fijo_y_pago_unico(self):
        renta = prediccion_mes(self.renta, HOY, 2026, 12)
        self.assertEqual((renta.monto, renta.fecha, renta.fuente, renta.exacto), (9777.0, date(2026, 12, 29), 'fijo', True))
        self.assertEqual(prediccion_mes(self.renta, HOY, 2027, 2).fecha, date(2027, 2, 28))   # día 29 en febrero
        self.assertEqual(prediccion_mes(self.tenencia, HOY, 2026, 12).monto, 3000.0)
        self.assertEqual(prediccion_mes(self.predial, HOY, 2026, 12).fuente, 'no_toca')

    def test_bimestral_no_toca_en_diciembre_y_si_en_enero(self):
        dic = prediccion_mes(self.luz, HOY, 2026, 12)
        self.assertEqual((dic.monto, dic.fuente), (0.0, 'no_toca'))
        self.assertEqual(dic.fecha, date(2027, 1, 21))            # vence 21/11 + 61 días
        self.assertIn('21 ene', dic.nota)
        ene = prediccion_mes(self.luz, HOY, 2027, 1)
        self.assertEqual((ene.monto, ene.fecha, ene.exacto, ene.fuente), (1200.0, date(2027, 1, 21), False, 'recibos'))
        nov = prediccion_mes(self.luz, HOY, 2026, 11)              # el recibo en mano vence este mes: monto exacto
        self.assertEqual((nov.monto, nov.exacto, nov.nota), (1100.0, True, 'recibo en mano'))

    def test_sin_recibos_usa_los_movimientos_por_palabra_completa(self):
        recibos = recibos_del_libro(self.gas, HOY)
        self.assertEqual([r.monto for r in recibos], [560.0, 580.0, 598.87])   # 'GASOLINA' no cuenta
        dic = prediccion_mes(self.gas, HOY, 2026, 12)
        self.assertEqual((dic.fuente, dic.fecha, dic.exacto), ('movimientos', date(2026, 12, 3), False))
        self.assertAlmostEqual(dic.monto, 618.49, places=2)        # tendencia +19/mes acotada al ±25%

    def test_sin_nada_que_predecir(self):
        self.assertEqual(prediccion_mes(self.agua, HOY, 2026, 12).fuente, 'sin_datos')
        self.agua.fecha_proximo_recibo = date(2026, 12, 10)       # lo capturado a mano sí cuenta si cae en el mes
        cap = prediccion_mes(self.agua, HOY, 2026, 12)
        self.assertEqual((cap.monto, cap.fuente), (300.0, 'capturado'))

    def test_plan_suma_el_mes_que_entra(self):
        plan = plan_quincenal(Presupuesto.objects.filter(propietario=self.user).order_by('id'), HOY)
        self.assertEqual(plan['mes_siguiente'], 'diciembre')
        self.assertEqual(plan['total_proximo_mes'], round(9777 + 618.49 + 3000, 2))
        self.assertEqual(plan['n_sin_datos'], 1)
        por = {f['p'].categoria: f['proximo_mes'] for f in plan['filas']}
        self.assertEqual(por['Luz'].fuente, 'no_toca')

    def test_estacionalidad_con_un_anio_de_recibos(self):
        R = lambda f, m: Recibo(f, None, m)
        hist = [R(date(2025, 7, 10), 1500), R(date(2025, 9, 9), 1400), R(date(2025, 11, 9), 900), R(date(2026, 1, 9), 800),
                R(date(2026, 3, 10), 850), R(date(2026, 5, 9), 1200), R(date(2026, 7, 10), 1600), R(date(2026, 9, 9), 1500),
                R(date(2026, 11, 9), 950)]
        monto, factor = estimar_para_fecha(hist, date(2027, 1, 21))   # enero: época barata → por debajo del promedio
        self.assertLess(monto, 1000)
        self.assertLess(factor, 1)
        monto, factor = estimar_para_fecha(hist, date(2027, 7, 22))   # julio: época cara
        self.assertGreater(monto, 1400)
        self.assertIsNone(estimar_para_fecha(hist[:3], date(2027, 1, 21))[1])   # pocos recibos: sin ajuste

    def test_recibos_duplicados_no_inundan_el_mes(self):
        dup = [Recibo(date(2026, 11, 9), None, 100.0)] * 3
        self.assertEqual(cadencia_dias([r.emision for r in dup], 'internet'), 30)   # gaps de 0 días no son ciclo
        self.assertEqual(len(pagos_en_mes(dup, 'internet', 2026, 12, HOY)), 1)
        self.assertEqual(prediccion_variable([Recibo(None, None, 500.0)], 'agua', 2026, 12, HOY).fuente, 'sin_datos')


class PaginaPresupuestoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.renta = Presupuesto.objects.create(propietario=self.user, categoria='Renta', monto_presupuestado=D('9777'), dia_pago=29)
        self.luz = Presupuesto.objects.create(propietario=self.user, categoria='Luz', monto_presupuestado=D('1100'))
        self.client.login(username='mau', password='x')

    def test_muestra_plan_y_botones_de_recibos_solo_en_variables(self):
        r = self.client.get(reverse('presupuesto'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Aparta cada quincena')
        self.assertContains(r, 'Monto fijo · día 29')
        self.assertContains(r, 'Recibo variable · cada ~61 días')
        self.assertContains(r, reverse('predecir_recibo_presupuesto', args=[self.luz.id]))
        self.assertNotContains(r, reverse('predecir_recibo_presupuesto', args=[self.renta.id]))
        self.assertEqual(r.context['total_quincena'], round(9777 / 2 + 1100 * 15 / 61, 2))

    def test_eliminar_solo_por_post_y_borra_historial(self):
        HistorialReciboServicio.objects.create(propietario=self.user, presupuesto=self.luz, monto_total=D('1'), archivo_drive_id='x')
        self.assertEqual(self.client.get(reverse('eliminar_presupuesto', args=[self.luz.id])).status_code, 405)
        r = self.client.post(reverse('eliminar_presupuesto', args=[self.luz.id]), follow=True)
        self.assertRedirects(r, reverse('presupuesto'))
        self.assertFalse(Presupuesto.objects.filter(id=self.luz.id).exists())
        self.assertEqual(HistorialReciboServicio.objects.count(), 0)
        otro = User.objects.create_user('otro', password='x')
        ajeno = Presupuesto.objects.create(propietario=otro, categoria='Gas')
        self.assertEqual(self.client.post(reverse('eliminar_presupuesto', args=[ajeno.id])).status_code, 404)

    def test_predecir_devuelve_el_mes_que_entra_y_guarda_el_siguiente_pago(self):
        for fecha, monto in [(date(2026, 9, 9), '1000'), (date(2026, 11, 9), '1100')]:
            HistorialReciboServicio.objects.create(propietario=self.user, presupuesto=self.luz, fecha_emision=fecha,
                                                   monto_total=D(monto), archivo_drive_id=f'luz-{fecha}')
        r = self.client.get(reverse('predecir_recibo_presupuesto', args=[self.luz.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['fuente'], 'recibos')
        self.assertIn(data['mes'], ('diciembre', 'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre'))
        self.assertIn('siguiente_pago', data)
        self.luz.refresh_from_db()
        self.assertEqual(str(self.luz.fecha_proximo_recibo), data['siguiente_pago']['fecha'])   # guardó el siguiente pago
        self.assertGreater(self.luz.monto_presupuestado, 0)
        self.assertContains(self.client.get(reverse('presupuesto')), 'Previsto para')

    def test_predecir_sin_recibos_ni_movimientos_explica_que_hacer(self):
        r = self.client.get(reverse('predecir_recibo_presupuesto', args=[self.luz.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertIn('procesa sus recibos', r.json()['error'])

    def test_recibos_no_aplican_a_monto_fijo(self):
        r = self.client.get(reverse('predecir_recibo_presupuesto', args=[self.renta.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400)
        self.assertIn('monto fijo', r.json()['error'])

    def test_formulario_valida_dia_de_pago(self):
        base = {'categoria': 'Renta', 'monto_presupuestado': '9777', 'monto_real': '0', 'es_recurrente': 'on'}
        self.assertFalse(PresupuestoForm({**base, 'dia_pago': '32'}).is_valid())
        self.assertFalse(PresupuestoForm({**base, 'dia_pago': '0'}).is_valid())
        self.assertTrue(PresupuestoForm({**base, 'dia_pago': '29'}).is_valid())
        self.assertTrue(PresupuestoForm({**base, 'dia_pago': ''}).is_valid())


class LoteDeRecibosTest(TestCase):
    """Un lote de Drive que murió a medias no debe bloquear los clics siguientes: solo se reutiliza
    el grupo en curso si sigue dentro de su plazo."""

    class Backend:
        def __init__(self): self.datos = {}
        def get(self, k): return self.datos.get(k)
        def set(self, k, v): self.datos[k] = v
        def delete(self, k): self.datos.pop(k, None)

    def test_plazo_del_lote(self):
        from unittest.mock import Mock
        from .tasks import _lote_vigente, _marcar_lote, _clave_lote
        app = Mock(); app.backend = self.Backend()
        self.assertFalse(_lote_vigente(app, 'g1'))                  # sin marca: perdido
        _marcar_lote(app, 'g1', 12)
        self.assertTrue(_lote_vigente(app, 'g1'))
        app.backend.datos[_clave_lote('g1')] = b'1.0'                # ya venció
        self.assertFalse(_lote_vigente(app, 'g1'))
        app.backend = Mock(get=Mock(side_effect=RuntimeError('sin redis')))
        self.assertFalse(_lote_vigente(app, 'g1'))                  # backend sin soporte: no bloquea

    def test_relanza_si_el_lote_anterior_vencio(self):
        from unittest.mock import Mock, patch
        from . import tasks
        tarea = Mock(); tarea.name = 'finanzas.tasks.process_single_utility_bill'; tarea.app.backend = self.Backend()
        viejo = Mock(); viejo.ready.return_value = False; viejo.__len__ = Mock(return_value=12)
        nuevo = Mock(id='finanzas.tasks.process_single_utility_bill-2')
        archivos = [{'id': 'a', 'name': 'a.pdf', 'mimeType': 'application/pdf'}]
        with patch.object(tasks.GroupResult, 'restore', return_value=viejo), \
             patch.object(tasks, 'group') as grupo:
            grupo.return_value.apply_async.return_value = nuevo
            r = tasks._lanzar_grupo(tarea, archivos, 2, 7)
            self.assertEqual(r['total_tasks'], 1)                     # lote nuevo, no el viejo de 12
            grupo.return_value.apply_async.assert_called_once_with(task_id='finanzas.tasks.process_single_utility_bill-2')
            nuevo.save.assert_called_once()
            # ahora sí hay un lote vigente: el segundo clic se pega a él
            r2 = tasks._lanzar_grupo(tarea, archivos, 2, 7)
            self.assertEqual(r2['total_tasks'], 12)
            grupo.return_value.apply_async.assert_called_once()
        tarea.app.backend.delete(tasks._clave_lote(nuevo.id))
        self.assertFalse(tasks._lote_vigente(tarea.app, nuevo.id))
