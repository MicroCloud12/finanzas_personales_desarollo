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

    def test_recibo_reciente_igual_proyecta_el_siguiente_ciclo(self):
        # Aunque el recibo de noviembre acabe de llegar y aún no venza, Estimado proyecta el siguiente recibo.
        fecha, monto, paso, facturado = estimacion(self.luz, HOY)
        self.assertEqual((fecha, monto, paso, facturado), (date(2027, 1, 9), 1200.0, 61, False))
        self.luz.refresh_from_db()
        self.assertEqual(self.luz.monto_presupuestado, D('0'))      # no toca lo guardado (eso lo hace Predecir)

    def test_recibo_sin_emision_usa_fecha_limite_como_respaldo(self):
        ultimo = self.luz.historial_recibos.order_by('-fecha_emision').first()
        ultimo.fecha_emision = None
        ultimo.datos_json = {'fecha_limite_pago': '2026-11-21'}
        ultimo.save()
        self.assertEqual(estimacion(self.luz, HOY)[:2], (date(2027, 1, 9), 1200.0))

    def test_recibo_ya_vencido_proyecta_el_siguiente_ciclo(self):
        fecha, monto, paso, facturado = estimacion(self.luz, date(2026, 12, 15))
        self.assertEqual((fecha, paso, facturado), (date(2027, 1, 9), 61, False))
        self.assertAlmostEqual(monto, 1200.0)                       # tendencia +100 por recibo

    def test_variable_sin_recibos_usa_lo_capturado(self):
        self.assertEqual(estimacion(self.internet, HOY), (date(2026, 12, 5), 599.0, 30, False))
        self.internet.fecha_proximo_recibo = date(2026, 11, 1)      # ya pasó: no se puede proyectar
        self.assertEqual(estimacion(self.internet, HOY)[0], None)

    def test_plan_reparte_cada_pago_en_sus_quincenas(self):
        plan = plan_quincenal(Presupuesto.objects.filter(propietario=self.user).order_by('id'), HOY)
        por = {f['p'].categoria: f for f in plan['filas']}
        self.assertEqual(por['Renta']['por_quincena'], 4888.5)             # mensual: mitad y mitad
        self.assertEqual(por['Luz']['por_quincena'], round(1200 * 15 / 61, 2))   # bimestral: sobre el próximo estimado
        self.assertEqual(por['Internet']['por_quincena'], 299.5)
        self.assertEqual(por['Tenencia']['por_quincena'], 1000.0)          # 3,000 el 20/12: quedan 3 quincenas
        self.assertEqual(plan['proxima_nomina'], date(2026, 11, 28))
        self.assertTrue(por['Muchacha']['vence_antes'])                    # 25/11 cae antes de la nómina del 28
        self.assertFalse(por['Luz']['vence_antes'])                        # el próximo recibo cae en enero
        self.assertFalse(por['Renta']['vence_antes'])                      # 29/11 ya es con la siguiente
        self.assertEqual((plan['vence_antes'], plan['n_vencen']), (1000.0, 1))
        self.assertEqual(plan['total_quincena'], round(4888.5 + 500 + 1200 * 15 / 61 + 299.5 + 1000, 2))


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

    def test_bimestral_pronostica_proximo_recibo_sin_importar_dias_faltantes(self):
        dic = prediccion_mes(self.luz, HOY, 2026, 12)
        self.assertEqual((dic.monto, dic.fecha, dic.exacto, dic.fuente), (1200.0, date(2027, 1, 9), False, 'recibos'))
        ene = prediccion_mes(self.luz, HOY, 2027, 1)
        self.assertEqual((ene.monto, ene.fecha, ene.exacto, ene.fuente), (1200.0, date(2027, 1, 9), False, 'recibos'))

    def test_recibo_mensual_recien_llegado_en_noviembre_pronostica_diciembre(self):
        hoy_nov = date(2026, 11, 25)
        telmex = Presupuesto.objects.create(propietario=self.user, categoria='Telmex', monto_presupuestado=D('0'))
        for fecha, limite, monto in [
            (date(2026, 9, 20), '2026-10-02', '500'),
            (date(2026, 10, 18), '2026-10-30', '550'),
            (date(2026, 11, 20), '2026-12-04', '600'),  # acaba de llegar y vence en dic: igual debe pronosticar el de dic
        ]:
            HistorialReciboServicio.objects.create(
                propietario=self.user, presupuesto=telmex, fecha_emision=fecha,
                monto_total=D(monto), datos_json={'fecha_limite_pago': limite}, archivo_drive_id=f'tel-{fecha}'
            )
        dic = prediccion_mes(telmex, hoy_nov, 2026, 12)
        self.assertEqual((dic.fecha, dic.exacto, dic.fuente), (date(2026, 12, 20), False, 'recibos'))
        self.assertAlmostEqual(dic.monto, 650.0)

    def test_sin_recibos_usa_los_movimientos_por_palabra_completa(self):
        recibos = recibos_del_libro(self.gas, HOY)
        self.assertEqual([r.monto for r in recibos], [560.0, 580.0, 598.87])   # 'GASOLINA' no cuenta
        dic = prediccion_mes(self.gas, HOY, 2026, 12)
        self.assertEqual((dic.fuente, dic.fecha, dic.exacto), ('movimientos', date(2026, 12, 3), False))
        self.assertAlmostEqual(dic.monto, 618.49, places=2)        # tendencia +19/mes acotada al ±25%

    def test_sin_nada_que_predecir(self):
        self.assertEqual(prediccion_mes(self.agua, HOY, 2026, 12).fuente, 'sin_datos')
        self.agua.fecha_proximo_recibo = date(2026, 12, 10)       # lo capturado a mano sí cuenta
        cap = prediccion_mes(self.agua, HOY, 2026, 12)
        self.assertEqual((cap.monto, cap.fuente), (300.0, 'capturado'))

    def test_plan_suma_el_mes_que_entra(self):
        plan = plan_quincenal(Presupuesto.objects.filter(propietario=self.user).order_by('id'), HOY)
        self.assertEqual(plan['mes_siguiente'], 'diciembre')
        self.assertEqual(plan['total_proximo_mes'], round(9777 + 1200 + 618.49 + 3000, 2))
        self.assertEqual(plan['n_sin_datos'], 1)
        por = {f['p'].categoria: f['proximo_mes'] for f in plan['filas']}
        self.assertEqual((por['Luz'].fuente, por['Luz'].monto), ('recibos', 1200.0))

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

    def test_predecir_usa_ia_con_consumo_estacionalidad_y_se_refleja_en_la_tabla(self):
        from unittest.mock import Mock, patch
        agua = Presupuesto.objects.create(propietario=self.user, categoria='Agua', monto_presupuestado=D('0'))
        for fecha, monto, consumo, periodo in [
            (date(2026, 9, 8), '680', '22 m3', '08 AGO - 07 SEP'),
            (date(2026, 11, 8), '1029', '36 m3', '08 OCT - 07 NOV'),
        ]:
            HistorialReciboServicio.objects.create(
                propietario=self.user, presupuesto=agua, fecha_emision=fecha, monto_total=D(monto),
                datos_json={'consumo': consumo, 'periodo_facturado': periodo, 'fecha_limite_pago': '2026-11-28'},
                archivo_drive_id=f'agua-{fecha}',
            )
        ia_mock = Mock()
        ia_mock.extract_from_text.return_value = {
            'monto_predicho': 710.0,
            'fecha_predicha': '2026-12-08',
            'consumo_estimado': '21 m3',
            'frecuencia_dias': 30,
            'razonamiento': 'En diciembre baja el consumo de agua por invierno respecto al pico de $1,029.',
        }
        with patch('finanzas.views.presupuesto.get_gemini_service', return_value=ia_mock):
            r = self.client.get(reverse('predecir_recibo_presupuesto', args=[agua.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        prompt_name, _, ctx_json = ia_mock.extract_from_text.call_args[0]
        self.assertEqual(prompt_name, 'prediccion_servicio')
        self.assertIn('36 m3', ctx_json)
        self.assertIn('08 OCT - 07 NOV', ctx_json)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual((data['fuente'], data['monto_predicho'], data['fecha_predicha']), ('ia', 710.0, '2026-12-08'))
        self.assertIn('invierno', data['mensaje'])

        agua.refresh_from_db()
        self.assertEqual((agua.monto_presupuestado, agua.fecha_proximo_recibo), (D('710.00'), date(2026, 12, 8)))

        # Al recargar la tabla debe respetarse el pronóstico IA ($710.00, 30 días), no pisarlo con la regresión lineal
        pagina = self.client.get(reverse('presupuesto'))
        self.assertContains(pagina, '710.00')
        self.assertContains(pagina, 'pronóstico IA')
        fila_agua = next(f for f in pagina.context['filas'] if f['p'].id == agua.id)
        self.assertEqual((fila_agua['estimado'], fila_agua['cada_dias'], fila_agua['proximo_mes'].monto), (710.0, 30, 710.0))

    def test_predecir_respalda_con_ajuste_estacional_si_la_api_de_ia_agota_cuota(self):
        from unittest.mock import Mock, patch
        agua = Presupuesto.objects.create(propietario=self.user, categoria='Agua', monto_presupuestado=D('0'))
        for fecha, monto in [(date(2026, 7, 8), '680'), (date(2026, 9, 8), '700'), (date(2026, 11, 8), '1029')]:
            HistorialReciboServicio.objects.create(
                propietario=self.user, presupuesto=agua, fecha_emision=fecha, monto_total=D(monto), archivo_drive_id=f'a-{fecha}'
            )
        ia_caida = Mock()
        ia_caida.extract_from_text.return_value = {'error': '429 Your prepayment credits are depleted'}
        with patch('finanzas.views.presupuesto.get_gemini_service', return_value=ia_caida):
            r = self.client.get(reverse('predecir_recibo_presupuesto', args=[agua.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['fuente'], 'estacional')
        self.assertLess(data['monto_predicho'], 800.0)   # invierno + amortiguación del pico de $1,029

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

    def test_editar_como_monto_fijo_sin_dia_de_pago(self):
        muchacha = Presupuesto.objects.create(propietario=self.user, categoria='Muchacha', monto_presupuestado=D('2000'))
        r_get = self.client.get(reverse('editar_presupuesto', args=[muchacha.id]))
        self.assertEqual(r_get.status_code, 200)
        self.assertContains(r_get, 'btn-modo-fijo')
        self.assertContains(r_get, 'Monto fijo')

        r_post = self.client.post(reverse('editar_presupuesto', args=[muchacha.id]), {
            'modo_selector': '1',
            'categoria': 'Muchacha',
            'es_fijo': 'on',
            'monto_presupuestado': '2000',
            'monto_real': '0',
            'dia_pago': '',
            'es_recurrente': 'on',
        }, follow=True)
        self.assertRedirects(r_post, reverse('presupuesto'))
        muchacha.refresh_from_db()
        self.assertTrue(muchacha.es_fijo)
        self.assertTrue(muchacha.usa_monto_fijo)
        self.assertIsNone(muchacha.dia_pago)
        self.assertContains(r_post, 'Monto fijo · mensual')
        self.assertContains(r_post, 'Cada mes')
        self.assertNotContains(r_post, reverse('predecir_recibo_presupuesto', args=[muchacha.id]))

        # Si luego lo cambia a recibo variable desde el selector, limpia es_fijo y dia_pago
        self.client.post(reverse('editar_presupuesto', args=[ self.renta.id ]), {
            'modo_selector': '1',
            'categoria': 'Renta',
            'monto_presupuestado': '9777',
            'monto_real': '0',
            'dia_pago': '29',
            'es_recurrente': 'on',
        })
        self.renta.refresh_from_db()
        self.assertFalse(self.renta.es_fijo)
        self.assertIsNone(self.renta.dia_pago)


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
