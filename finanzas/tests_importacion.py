"""
Pruebas de la importación de CSV (finanzas/importacion.py y el botón "Subir CSV").

Correr:  python manage.py test finanzas.tests_importacion
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .importacion import aplicar_alias, coincidencias, conciliar, decodificar, importar, leer_csv
from .models import AliasComercio, Cuenta, Deuda, registro_transacciones

D = Decimal

SANTANDER = """FECHA,HORA,SUCURSAL,CONCEPTO,RETIRO,DEPÓSITO,SALDO,REFERENCIA
11/6/2026,14:04:47,784,SUPER RIDES      CIUDAD DE MEX   7696182,-201,,4018.18,44705
11/6/2026,7:49:05,784,SUPER RIDES      CIUDAD DE MEX   7696182,-201,,4665.2,90590
11/5/2026,23:49:11,784,DLO*UBER RIDE    CIUDAD DE MEX   9848768,-168.88,,4965.09,91132
11/5/2026,11:47:48,784,OXXO PEDREGAL    MEXICO DF       6544845,-70,,5411.03,74856
10/30/2026,9:00:00,784,ABONO NOMINA EMPRESA SA         1234567,,23827.49,9000,11111
10/30/2026,9:10:00,784,TRANSFERENCIA A MAURICIO NU     2222222,-4888,,4112,22222
10/30/2026,9:20:00,784,TIENDA RARA      CIUDAD DE MEX   3333333,-99.5,,4012.5,33333
,,,,,,,
,,,,,,,
"""

PROPIO = """Usuario,Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino,Nota
otro_usuario,05/11/2026,UBER,Transporte,168.88,gasto,Santander,,
otro_usuario,06/11/2026,SUPER RIDES,Transporte,201.00,gasto,Santander,,
otro_usuario,06/11/2026,SUPER RIDES,Transporte,201.00,gasto,Santander,,
otro_usuario,30/10/2026,NÓMINA,Nomina,23827.49,ingreso,Santander,,
otro_usuario,30/10/2026,APARTADO RENTA,Transferencia,4888,transferencia,Santander,NU (Debito),
"""


class LeerCsvTest(TestCase):

    def test_santander_se_detecta_y_se_convierte(self):
        filas, es_santander = leer_csv(SANTANDER)
        self.assertTrue(es_santander)
        self.assertEqual(len(filas), 7)                       # los renglones vacíos no cuentan
        self.assertEqual([f['fecha'] for f in filas][:3], [date(2026, 10, 30)] * 3)   # m/d/aaaa y orden por fecha y hora
        nomina = filas[0]
        self.assertEqual((nomina['tipo'], nomina['descripcion'], nomina['categoria'], nomina['monto'], nomina['destino']),
                         ('INGRESO', 'NÓMINA', 'Nomina', D('23827.49'), 'Santander'))
        nu = filas[1]
        self.assertEqual((nu['tipo'], nu['origen'], nu['destino'], nu['monto']), ('TRANSFERENCIA', 'Santander', 'NU (Debito)', D('4888')))
        rara = filas[2]
        self.assertEqual((rara['descripcion'], rara['categoria'], rara['tipo'], rara['origen']), ('TIENDA RARA', 'Gastos varios', 'GASTO', 'Santander'))
        self.assertTrue(rara['nota'].startswith('Revisar'))
        self.assertEqual([f['descripcion'] for f in filas[3:]], ['OXXO', 'UBER', 'DIDI', 'DIDI'])
        self.assertEqual([f['banco'] for f in filas[5:]], ['SUPER RIDES', 'SUPER RIDES'])   # el banco lo escribe así; DiDi es quien cobra

    def test_formato_propio_y_delimitador_punto_y_coma(self):
        filas, es_santander = leer_csv(PROPIO)
        self.assertFalse(es_santander)
        self.assertEqual(len(filas), 5)
        self.assertEqual(filas[0]['usuario'], 'otro_usuario')
        self.assertEqual(filas[3]['monto'], D('23827.49'))
        con_pyc = PROPIO.replace(',', ';')
        self.assertEqual(len(leer_csv(con_pyc)[0]), 5)

    def test_errores_dicen_la_fila(self):
        with self.assertRaisesMessage(ValueError, 'fila 3'):
            leer_csv("Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n"
                     "01/11/2026,A,B,10,gasto,Santander,\n01/11/2026,A,B,diez,gasto,Santander,\n")
        with self.assertRaisesMessage(ValueError, 'Tipo'):
            leer_csv("Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n01/11/2026,A,B,10,compra,Santander,\n")
        with self.assertRaisesMessage(ValueError, 'no reconozco las columnas'):
            leer_csv("a,b,c\n1,2,3\n")

    def test_decodificar_acepta_excel_windows(self):
        self.assertEqual(decodificar("NÓMINA".encode('cp1252')), "NÓMINA")
        self.assertEqual(decodificar("﻿NÓMINA".encode('utf-8')), "NÓMINA")


class ImportarTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.santander = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO', saldo_inicial=D('10000'))
        self.nu = Cuenta.objects.create(propietario=self.user, nombre='NU (Debito)', tipo='DEBITO')

    def test_importa_y_no_duplica_al_repetir(self):
        filas, _ = leer_csv(PROPIO)
        r = importar(self.user, filas)
        self.assertEqual((r['insertados'], r['omitidos'], r['sin_cuenta']), (5, 0, {}))
        self.assertEqual(registro_transacciones.objects.filter(descripcion='SUPER RIDES').count(), 2)  # dos viajes iguales (formato propio: tal cual)
        r = importar(self.user, filas)
        self.assertEqual((r['insertados'], r['omitidos']), (0, 5))
        self.assertEqual(self.santander.saldo(), D('10000') + D('23827.49') - D('4888') - D('168.88') - D('402'))
        self.assertEqual(self.nu.saldo(), D('4888'))

    def test_cuenta_desconocida_se_reporta_y_queda_sin_ligar(self):
        filas, _ = leer_csv("Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n"
                            "01/11/2026,CAFE,Comida,50,gasto,Klar,\n")
        r = importar(self.user, filas)
        self.assertEqual(r['sin_cuenta'], {'Klar': 1})
        t = registro_transacciones.objects.get(descripcion='CAFE')
        self.assertIsNone(t.origen)
        self.assertEqual(t.cuenta_origen, 'Klar')

    def test_pago_a_prestamo_aplica_regla_del_libro(self):
        prestamo = Deuda.objects.create(propietario=self.user, nombre='Digitt', tipo_deuda='PRESTAMO',
                                        monto_total=D('10000'), tasa_interes=D('30'), plazo_meses=12)
        filas, _ = leer_csv("Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n"
                            "29/10/2026,PAGO DIGITT,Deudas,888,transferencia,Santander,Digitt\n")
        importar(self.user, filas)
        t = registro_transacciones.objects.get(descripcion='PAGO DIGITT')
        self.assertEqual(t.tipo, 'PAGO_MENSUALIDAD')
        self.assertEqual(t.destino, prestamo.cuenta)


class CoincidenciasTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.santander = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO')
        self.amex = Deuda.objects.create(propietario=self.user, nombre='AMEX', tipo_deuda='TARJETA_CREDITO',
                                         monto_total=D('20000'), tasa_interes=D('60'), plazo_meses=1).cuenta

    def mov(self, tipo, monto, fecha, descripcion, origen=None, destino=None):
        return registro_transacciones.objects.create(propietario=self.user, fecha=fecha, descripcion=descripcion,
                                                     categoria='X', monto=D(str(monto)), tipo=tipo, origen=origen, destino=destino)

    def test_mismo_monto_fecha_cercana_y_direccion(self):
        uber = self.mov('GASTO', 168.88, date(2026, 11, 4), 'Uber', origen=self.santander)        # ticket un día antes
        self.mov('GASTO', 201, date(2026, 11, 6), 'Super Rides', origen=self.santander)           # solo uno de los dos viajes
        self.mov('INGRESO', 70, date(2026, 11, 5), 'Devolución', destino=self.santander)          # mismo monto que el OXXO pero ENTRA
        self.mov('GASTO', 416.10, date(2026, 11, 20), 'Rappi', origen=self.santander)             # muy lejos (14 días)
        filas, _ = leer_csv(SANTANDER)
        iguales = coincidencias(self.user, filas)
        por_desc = {(f['descripcion'], str(f['monto'])): c for f, c in zip(filas, iguales)}
        self.assertEqual(por_desc[('UBER', '168.88')]['id'], uber.id)
        self.assertFalse(por_desc[('UBER', '168.88')]['exacta'])
        self.assertEqual(por_desc[('UBER', '168.88')]['cuenta'], 'Santander')
        self.assertIsNone(por_desc[('OXXO', '70')])             # dirección distinta: no es el mismo
        # dos SUPER RIDES de 201: solo uno está registrado -> uno coincide y el otro es nuevo
        rides = [c for f, c in zip(filas, iguales) if f['banco'] == 'SUPER RIDES']
        self.assertEqual(sum(1 for c in rides if c), 1)
        self.assertIsNone(por_desc[('NÓMINA', '23827.49')])

    def test_exacta_cuando_misma_fecha_y_descripcion(self):
        self.mov('GASTO', 70, date(2026, 11, 5), 'oxxo', origen=self.santander)
        filas, _ = leer_csv(SANTANDER)
        c = next(c for f, c in zip(filas, iguales) if f['descripcion'] == 'OXXO') if (iguales := coincidencias(self.user, filas)) else None
        self.assertTrue(c['exacta'])


class BotonSubirCsvTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.otro = User.objects.create_user('otro_usuario', password='x')
        self.santander = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO', saldo_inicial=D('1000'))
        Cuenta.objects.create(propietario=self.user, nombre='NU (Debito)', tipo='DEBITO')
        self.client.login(username='mau', password='x')

    def subir(self, nombre, contenido):
        archivo = SimpleUploadedFile(nombre, contenido.encode('utf-8'), content_type='text/csv')
        return self.client.post(reverse('subir_csv'), {'archivo': archivo})

    def mensajes(self, r):
        # Los mensajes se acumulan en la sesión del cliente de pruebas: el último es el de esta petición.
        return [m.message for m in get_messages(r.wsgi_request)]

    def test_boton_visible_y_sube_archivo_de_santander_en_dos_pasos(self):
        r = self.client.get(reverse('lista_transacciones'))
        self.assertContains(r, 'Subir CSV')
        self.assertContains(r, reverse('subir_csv'))
        # 1) revisar: no se guarda nada todavía
        r = self.subir('MOVIMIENTOS_CUENTA_2790.csv', SANTANDER)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Revisar antes de guardar')
        self.assertEqual(r.context['nuevos'], 7)
        self.assertEqual(r.context['repetidos'], 0)
        self.assertEqual(registro_transacciones.objects.count(), 0)
        # 2) confirmar todos
        r = self.client.post(reverse('confirmar_csv'), {'fila': [str(x['i']) for x in r.context['renglones']]})
        self.assertRedirects(r, reverse('lista_transacciones') + '?year=2026&month=11', fetch_redirect_response=False)
        self.assertIn('7 movimientos guardados', self.mensajes(r)[-1])
        self.assertEqual(registro_transacciones.objects.filter(propietario=self.user).count(), 7)
        # subirlo otra vez: todo aparece como ya registrado y desmarcado
        r = self.subir('MOVIMIENTOS_CUENTA_2790.csv', SANTANDER)
        self.assertEqual((r.context['nuevos'], r.context['repetidos']), (0, 7))
        self.assertTrue(all(not x['marcar'] for x in r.context['renglones']))
        self.assertContains(r, 'Ya registrado')

    def test_duplicados_por_monto_y_fecha_cercana_quedan_desmarcados(self):
        registro_transacciones.objects.create(propietario=self.user, fecha=date(2026, 11, 4), descripcion='Uber',
                                              categoria='Transporte', monto=D('168.88'), tipo='GASTO', origen=self.santander)
        r = self.subir('MOVIMIENTOS_CUENTA_2790.csv', SANTANDER)
        self.assertEqual((r.context['nuevos'], r.context['repetidos']), (6, 1))
        self.assertContains(r, 'Parece duplicado')
        self.assertContains(r, 'ya tienes: Uber')
        # solo se guardan los marcados
        marcados = [str(x['i']) for x in r.context['renglones'] if x['marcar']]
        self.client.post(reverse('confirmar_csv'), {'fila': marcados})
        self.assertEqual(registro_transacciones.objects.count(), 1 + 6)
        self.assertEqual(registro_transacciones.objects.filter(monto=D('168.88')).count(), 1)

    def test_historial_rellena_categoria_de_comercio_desconocido(self):
        registro_transacciones.objects.create(propietario=self.user, fecha=date(2026, 10, 1), descripcion='TIENDA RARA',
                                              categoria='Mascotas', monto=D('10'), tipo='GASTO', origen=self.santander)
        r = self.subir('MOVIMIENTOS_CUENTA_2790.csv', SANTANDER)
        rara = next(x['fila'] for x in r.context['renglones'] if x['fila']['descripcion'] == 'TIENDA RARA')
        self.assertEqual((rara['categoria'], rara['nota']), ('Mascotas', ''))
        self.assertEqual(r.context['por_revisar'], 0)

    def test_formato_propio_siempre_va_al_usuario_que_sube(self):
        r = self.subir('movs.csv', PROPIO)      # la columna Usuario dice 'otro_usuario'
        self.client.post(reverse('confirmar_csv'), {'fila': [str(x['i']) for x in r.context['renglones']]})
        self.assertEqual(registro_transacciones.objects.filter(propietario=self.user).count(), 5)
        self.assertEqual(registro_transacciones.objects.filter(propietario=self.otro).count(), 0)

    def test_archivo_malo_no_guarda_nada(self):
        r = self.subir('malo.csv', "Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n"
                                  "01/11/2026,A,B,10,gasto,Santander,\n02/11/2026,A,B,x,gasto,Santander,\n")
        self.assertIn('No pude leer malo.csv: fila 3', self.mensajes(r)[-1])
        self.assertEqual(registro_transacciones.objects.count(), 0)
        r = self.client.post(reverse('subir_csv'), {})
        self.assertIn('Elige un archivo', self.mensajes(r)[-1])
        r = self.client.post(reverse('confirmar_csv'), {'fila': ['0']})     # sin archivo pendiente
        self.assertIn('vuelve a subirlo', self.mensajes(r)[-1])

    def test_cuenta_desconocida_avisa_al_guardar(self):
        r = self.subir('movs.csv', "Fecha,Descripcion,Categoria,Monto,Tipo,Cuenta de origen,Cuenta de destino\n"
                                  "01/11/2026,CAFE,Comida,50,gasto,Klar,\n")
        r = self.client.post(reverse('confirmar_csv'), {'fila': ['0']})
        self.assertTrue(any("La cuenta 'Klar'" in m for m in self.mensajes(r)))

    def test_encabezado_con_preambulo_de_santander(self):
        con_preambulo = "Detalle del 11/01/2026 al 11/30/2026 de la cuenta 20**2790\n,Número de registros: 86\n\n\n" + SANTANDER
        filas, es_santander = leer_csv(con_preambulo)
        self.assertTrue(es_santander)
        self.assertEqual(len(filas), 7)


class AliasComercioTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO')
        Cuenta.objects.create(propietario=self.user, nombre='NU (Debito)', tipo='DEBITO')
        self.client.login(username='mau', password='x')

    def subir(self):
        archivo = SimpleUploadedFile('MOVIMIENTOS_CUENTA_2790.csv', SANTANDER.encode('utf-8'), content_type='text/csv')
        return self.client.post(reverse('subir_csv'), {'archivo': archivo})

    def test_corregir_en_pantalla_se_aprende_y_se_aplica_la_proxima_vez(self):
        r = self.subir()
        renglones = r.context['renglones']
        self.assertContains(r, 'name="desc_0"')          # descripción y categoría editables
        self.assertContains(r, 'list="categorias"')
        rides = [x for x in renglones if x['fila']['banco'] == 'SUPER RIDES']
        rara = next(x for x in renglones if x['fila']['descripcion'] == 'TIENDA RARA')
        self.assertEqual(rides[0]['fila']['banco'], 'SUPER RIDES')
        datos = {'fila': [str(x['i']) for x in renglones]}
        for x in renglones:
            datos[f"desc_{x['i']}"] = x['fila']['descripcion']
            datos[f"cat_{x['i']}"] = x['fila']['categoria']
        for x in rides:                                   # el usuario prefiere verlos como 'DiDi viaje'
            datos[f"desc_{x['i']}"] = 'DiDi viaje'
        datos[f"cat_{rara['i']}"] = 'Mascotas'            # solo cambia la categoría
        r = self.client.post(reverse('confirmar_csv'), datos)
        self.assertIn('Aprendí 2 nombres', [m.message for m in get_messages(r.wsgi_request)][-1])
        self.assertEqual(registro_transacciones.objects.filter(descripcion='DiDi viaje').count(), 2)
        self.assertEqual(registro_transacciones.objects.filter(descripcion='DIDI').count(), 0)
        self.assertEqual(registro_transacciones.objects.get(descripcion='TIENDA RARA').categoria, 'Mascotas')
        alias = {a.texto_banco: (a.descripcion, a.categoria) for a in AliasComercio.objects.filter(propietario=self.user)}
        self.assertEqual(alias, {'SUPER RIDES': ('DiDi viaje', 'Transporte'), 'TIENDA RARA': ('TIENDA RARA', 'Mascotas')})

        # la próxima subida ya viene con sus nombres, sin nota de revisar, y el alias manda sobre las reglas
        r = self.subir()
        filas = [x['fila'] for x in r.context['renglones']]
        self.assertEqual([f['descripcion'] for f in filas if f['banco'] == 'SUPER RIDES'], ['DiDi viaje', 'DiDi viaje'])
        rara = next(f for f in filas if f['banco'] == 'TIENDA RARA')
        self.assertEqual((rara['descripcion'], rara['categoria'], rara['nota']), ('TIENDA RARA', 'Mascotas', ''))
        self.assertEqual(r.context['repetidos'], 7)       # y todo se reconoce como ya registrado

    def test_alias_en_formato_propio_y_en_funcion(self):
        AliasComercio.objects.create(propietario=self.user, texto_banco='UBER', descripcion='Uber viajes', categoria='')
        filas, _ = leer_csv(PROPIO)
        aplicar_alias(self.user, filas)
        uber = next(f for f in filas if f['banco'] == 'UBER')
        self.assertEqual((uber['descripcion'], uber['categoria']), ('Uber viajes', 'Transporte'))  # sin categoría en el alias: se queda la del archivo


ESTADO_CUENTA = """FECHA,HORA,SUCURSAL,CONCEPTO,RETIRO,DEPÓSITO,SALDO,REFERENCIA
11/3/2026,10:00:00,784,PAGOAMEX         CIUDAD DE MEX   1111111,-1000,,7800,1
11/2/2026,13:00:00,784,RAPPI            CIUDAD DE MEX   2222222,-200,,8800,2
11/2/2026,12:00:00,784,DLO*UBER RIDE    CIUDAD DE MEX   3333333,-150,,9000,3
11/1/2026,09:00:00,784,ABONO NOMINA EMPRESA SA         4444444,,5000,9150,4
11/1/2026,08:00:00,784,OXXO PEDREGAL    MEXICO DF       5555555,-50,,4150,5
"""


class ConciliarTest(TestCase):
    """El banco abre el 1/11 con 4,200 y cierra el 3/11 con 7,800. En la app: saldo inicial 4,300 (100 de más),
    el Uber con fecha 31/10 (desfasado), el pago a AMEX dos veces (duplicado) y falta el Rappi."""

    def setUp(self):
        self.user = User.objects.create_user('mau', password='x')
        self.santander = Cuenta.objects.create(propietario=self.user, nombre='Santander', tipo='DEBITO',
                                               es_principal=True, saldo_inicial=D('4300'))
        self.amex = Cuenta.objects.create(propietario=self.user, nombre='AMEX', tipo='CREDITO')
        crear = registro_transacciones.objects.create
        crear(propietario=self.user, fecha=date(2026, 11, 1), descripcion='Oxxo', categoria='Tiendas', monto=D('50'), tipo='GASTO', origen=self.santander)
        crear(propietario=self.user, fecha=date(2026, 11, 1), descripcion='Nómina', categoria='Nomina', monto=D('5000'), tipo='INGRESO', destino=self.santander)
        crear(propietario=self.user, fecha=date(2026, 10, 31), descripcion='Uber', categoria='Transporte', monto=D('150'), tipo='GASTO', origen=self.santander)
        for _ in range(2):
            crear(propietario=self.user, fecha=date(2026, 11, 3), descripcion='Pago AMEX', categoria='Deudas', monto=D('1000'),
                  tipo='TRANSFERENCIA', origen=self.santander, destino=self.amex)
        self.client.login(username='mau', password='x')

    def test_conciliar_explica_la_diferencia(self):
        filas, _ = leer_csv(ESTADO_CUENTA)
        self.assertEqual([f['saldo'] for f in filas], [D('4150'), D('9150'), D('9000'), D('8800'), D('7800')])
        self.assertEqual([f['entra'] for f in filas], [False, True, False, False, False])
        r = conciliar(self.user, self.santander, filas)
        self.assertEqual((r['inicio'], r['fin']), (date(2026, 11, 1), date(2026, 11, 3)))
        self.assertEqual((r['banco_inicio'], r['banco_fin']), (D('4200'), D('7800')))
        self.assertEqual((r['app_inicio'], r['app_fin']), (D('4150'), D('7100')))      # el Uber del 31/10 ya está descontado
        self.assertEqual((r['dif_inicio'], r['dif_fin']), (D('-50'), D('-700')))
        self.assertEqual(r['coinciden'], 3)                                              # Oxxo, nómina, un pago AMEX
        self.assertEqual([t.descripcion for t in r['solo_app']], ['Pago AMEX'])
        self.assertEqual([filas[i]['descripcion'] for i in r['solo_banco']], ['RAPPI'])
        self.assertEqual([(filas[i]['banco'], t.descripcion) for i, t in r['desfasados']], [('DLO*UBER RIDE', 'Uber')])
        self.assertEqual((r['neto_solo_app'], r['neto_solo_banco'], r['neto_desfasados']), (D('-1000'), D('-200'), D('-150')))
        self.assertEqual(r['resto'], 0)   # dif_fin = dif_inicio + solo_app - solo_banco - desfasados
        self.assertEqual(r['ajuste_inicial'], D('-100'))   # los 100 de más del saldo inicial; el Uber desfasado no cuenta

    def test_sin_columna_saldo_no_se_puede_conciliar(self):
        filas, _ = leer_csv(PROPIO)
        with self.assertRaises(ValueError):
            conciliar(self.user, self.santander, filas)

    def test_pantalla_y_botones(self):
        r = self.client.get(reverse('resumen'))
        self.assertContains(r, reverse('conciliar_csv'))
        archivo = SimpleUploadedFile('MOVIMIENTOS_CUENTA_2790.csv', ESTADO_CUENTA.encode('utf-8'), content_type='text/csv')
        r = self.client.post(reverse('conciliar_csv'), {'archivo': archivo, 'cuenta': self.santander.id})
        self.assertRedirects(r, reverse('conciliar_csv'), fetch_redirect_response=False)
        r = self.client.get(reverse('conciliar_csv'))
        self.assertContains(r, 'Conciliación de Santander con el banco')
        self.assertEqual((r.context['banco_fin'], r.context['app_fin'], r.context['dif_fin']), (D('7800'), D('7100'), D('-700')))
        self.assertFalse(r.context['cuadra'])
        self.assertContains(r, 'Están en la app pero no en el banco (1)')
        self.assertContains(r, 'Están en el banco pero no en la app (1)')
        self.assertContains(r, 'fuera del periodo (1)')

        # 1) borrar el pago AMEX duplicado
        duplicado = r.context['solo_app'][0]
        r = self.client.post(reverse('conciliar_accion'), {'accion': 'eliminar', 'id': [str(duplicado.id)]})
        self.assertRedirects(r, reverse('conciliar_csv'), fetch_redirect_response=False)
        self.assertFalse(registro_transacciones.objects.filter(id=duplicado.id).exists())
        self.assertEqual(registro_transacciones.objects.filter(descripcion='Pago AMEX').count(), 1)
        # 2) agregar el Rappi que faltaba
        r = self.client.get(reverse('conciliar_csv'))
        self.assertEqual(r.context['dif_fin'], D('300'))
        indice = r.context['solo_banco'][0]['i']
        r = self.client.post(reverse('conciliar_accion'), {'accion': 'agregar', 'id': [str(indice)]})
        rappi = registro_transacciones.objects.get(descripcion='RAPPI')
        self.assertEqual((rappi.monto, rappi.tipo, rappi.origen, rappi.fecha), (D('200'), 'GASTO', self.santander, date(2026, 11, 2)))
        r = self.client.get(reverse('conciliar_csv'))
        self.assertEqual(r.context['dif_fin'], D('100'))   # lo que sobra del saldo inicial
        self.assertContains(r, 'Ajustar el saldo inicial de Santander en −$100.00')
        # 3) ajustar el saldo inicial: quita los 100 de más y respeta el Uber desfasado
        self.client.post(reverse('conciliar_accion'), {'accion': 'saldo_inicial'})
        self.santander.refresh_from_db()
        self.assertEqual(self.santander.saldo_inicial, D('4200'))
        r = self.client.get(reverse('conciliar_csv'))
        self.assertTrue(r.context['cuadra'])          # -150 de inicio y +150 del Uber desfasado se cancelan
        self.assertContains(r, 'CUADRA')
        self.assertEqual(r.context['ajuste_inicial'], 0)
        self.assertNotContains(r, 'Ajustar el saldo inicial')

    def test_sin_archivo_regresa_al_resumen(self):
        r = self.client.get(reverse('conciliar_csv'))
        self.assertRedirects(r, reverse('resumen'), fetch_redirect_response=False)
        r = self.client.post(reverse('conciliar_csv'), {'archivo': SimpleUploadedFile('x.csv', PROPIO.encode('utf-8')), 'cuenta': self.santander.id})
        self.assertRedirects(r, reverse('resumen'), fetch_redirect_response=False)
        self.assertIn('columna SALDO', [m.message for m in get_messages(r.wsgi_request)][-1])
